#!/usr/bin/env python3
"""Private Linphone 5.4 process for the BTicino C100X integration.

This program is GPLv3 because it is distributed with and links to Liblinphone.
It deliberately exposes only a small, versioned, local Unix-socket protocol.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import json
import os
import selectors
import signal
import socket
import struct
import time
from pathlib import Path
from typing import Any

import linphone

PROTOCOL = 1
VERSION = "0.1.0"
ITERATE_SECONDS = 0.02


class Runtime:
    def __init__(self, socket_path: Path) -> None:
        self.socket_path = socket_path
        self.selector = selectors.DefaultSelector()
        self.server: socket.socket | None = None
        self.client: socket.socket | None = None
        self.in_buffer = bytearray()
        self.out_buffer = bytearray()
        self.running = True
        self.shutdown_requested = False
        self.core = None
        self.core_listener = None
        self.call = None
        self.incoming_call = None
        self.incoming_deadline = 0.0
        self.domain: str | None = None
        self.message = None
        self.message_listener = None
        self.call_callbacks = None
        self.setup_deadline = 0.0
        self.media_deadline = 0.0
        self.media_started = False
        self.last_bandwidth_emit = 0.0
        self.media_path: str | None = None
        self.media_guard_fd: int | None = None
        self.snapshot_path: str | None = None
        self.microphone_enabled = False
        self.microphone_fd: int | None = None
        self.microphone_queue: list[bytes] = []

    def emit(self, event: str, **values: Any) -> None:
        self._queue({"event": event, **values})

    def reply(self, request_id: int, **values: Any) -> None:
        self._queue({"id": request_id, **values})

    def _queue(self, value: dict[str, Any]) -> None:
        self.out_buffer.extend(json.dumps(value, separators=(",", ":")).encode() + b"\n")

    def serve(self) -> None:
        self.socket_path.unlink(missing_ok=True)
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(self.socket_path))
        os.chmod(self.socket_path, 0o600)
        self.server.listen(1)
        self.server.setblocking(False)
        self.selector.register(self.server, selectors.EVENT_READ)
        while self.running:
            for key, mask in self.selector.select(ITERATE_SECONDS):
                if key.fileobj is self.server:
                    self._accept()
                elif key.fileobj is self.client:
                    self._service_client(mask)
            if self.core is not None:
                self.core.iterate()
            self._pump_microphone()
            self._watchdogs()
            if self.shutdown_requested and not self.out_buffer:
                self.running = False
        self.close()

    def _accept(self) -> None:
        assert self.server
        connection, _ = self.server.accept()
        if self.client is not None:
            connection.close()
            return
        connection.setblocking(False)
        self.client = connection
        self.selector.register(connection, selectors.EVENT_READ | selectors.EVENT_WRITE)

    def _service_client(self, mask: int) -> None:
        assert self.client
        if mask & selectors.EVENT_READ:
            data = self.client.recv(65536)
            if not data:
                self.running = False
                return
            self.in_buffer.extend(data)
            while b"\n" in self.in_buffer:
                line, _, remainder = self.in_buffer.partition(b"\n")
                self.in_buffer = bytearray(remainder)
                self._dispatch(line)
        if mask & selectors.EVENT_WRITE and self.out_buffer:
            sent = self.client.send(self.out_buffer)
            del self.out_buffer[:sent]

    def _dispatch(self, line: bytes) -> None:
        request_id = 0
        try:
            request = json.loads(line)
            request_id = int(request["id"])
            command = str(request["command"])
            handler = getattr(self, "command_" + command, None)
            if handler is None:
                raise ValueError("unsupported command")
            result = handler(request) or {}
            self.reply(request_id, **result)
        except Exception as error:
            # Never leak SIP credentials, certificate material, paths or payloads.
            self.reply(request_id, error=type(error).__name__)

    def command_hello(self, _request: dict[str, Any]) -> dict[str, Any]:
        return {"protocol": PROTOCOL, "version": VERSION, "linphone": "5.4"}

    def command_self_test(self, _request: dict[str, Any]) -> dict[str, Any]:
        """Exercise the exact binding surface without network or credentials."""
        factory = linphone.Factory.get()
        core = factory.create_core(None, None, None)
        required_core = (
            "add_auth_info",
            "add_proxy_config",
            "add_listener",
            "create_address",
            "create_call_params",
            "create_proxy_config",
            "invite_address_with_params",
            "set_media_encryption_mandatory",
            "set_user_agent",
        )
        missing = [f"Core.{name}" for name in required_core if not hasattr(type(core), name)]
        params = core.create_call_params(None)
        required_params = (
            "add_custom_sdp_attribute",
            "audio_direction",
            "media_encryption",
            "mic_enabled",
            "record_file",
            "video_direction",
        )
        missing.extend(
            f"CallParams.{name}" for name in required_params if not hasattr(type(params), name)
        )
        for name in (
            "create_auth_info",
            "create_call_listener",
            "create_chat_message_listener",
            "create_core_listener",
        ):
            if not hasattr(type(factory), name):
                missing.append(f"Factory.{name}")
        auth = factory.create_auth_info("self-test", None, "example.invalid")
        for name in ("domain", "password", "tls_cert_path", "tls_key_path"):
            if not hasattr(type(auth), name):
                missing.append(f"AuthInfo.{name}")
        listeners = (
            (factory.create_core_listener(), ("on_call_state_changed", "on_registration_state_changed")),
            (factory.create_call_listener(), ("on_next_video_frame_decoded",)),
            (factory.create_chat_message_listener(), ("on_msg_state_changed",)),
        )
        for listener, names in listeners:
            missing.extend(
                f"{type(listener).__name__}.{name}"
                for name in names
                if not hasattr(type(listener), name)
            )
        enum_members = (
            (linphone.MediaEncryption, "MediaEncryptionSRTP"),
            (linphone.MediaDirection, "MediaDirectionSendRecv"),
            (linphone.MediaDirection, "MediaDirectionRecvOnly"),
            (linphone.RegistrationState, "RegistrationStateOk"),
            (linphone.CallState, "CallStateStreamsRunning"),
            (linphone.ChatMessageState, "ChatMessageStateDelivered"),
            (linphone.Reason, "ReasonBusy"),
        )
        missing.extend(
            f"{enum_type.__name__}.{name}"
            for enum_type, name in enum_members
            if not hasattr(enum_type, name)
        )
        return {"binding": "ok" if not missing else "mismatch", "missing": missing}

    def command_register(self, request: dict[str, Any]) -> None:
        if self.core is not None:
            raise RuntimeError("already configured")
        factory = linphone.Factory.get()
        callbacks = factory.create_core_listener()
        callbacks.on_registration_state_changed = self._registration_changed
        callbacks.on_call_state_changed = self._call_state_changed
        callbacks.on_message_received = self._message_received
        core = factory.create_core(None, None, None)
        core.add_listener(callbacks)
        self.core_listener = callbacks
        core.max_calls = 1
        core.set_user_agent("VctLinphoneService", "1.8.4")
        core.root_ca = request["ca_path"]
        core.tls_cert_path = request["certificate_path"]
        core.tls_key_path = request["private_key_path"]
        core.verify_server_certificates(True)
        core.media_encryption = linphone.MediaEncryption.MediaEncryptionSRTP
        core.set_media_encryption_mandatory(True)
        core.video_capture_enabled = False
        core.video_display_enabled = False
        core.mic_enabled = False
        microphone_path = Path(request["microphone_path"])
        microphone_path.unlink(missing_ok=True)
        os.mkfifo(microphone_path, 0o600)
        self.microphone_fd = os.open(microphone_path, os.O_RDWR | os.O_NONBLOCK)
        os.write(self.microphone_fd, self._wav_header())
        core.use_files = True
        core.play_file = str(microphone_path)

        identity = core.create_address("sip:" + request["sip_uri"])
        self.domain = request["domain"]
        proxy = core.create_proxy_config()
        proxy.identity_address = identity
        proxy.server_addr = request["proxy"]
        proxy.routes = [request["proxy"]]
        proxy.expires = int(request.get("expires", 5184000))
        proxy.register_enabled = True
        core.add_proxy_config(proxy)
        auth = factory.create_auth_info(request["username"], None, request["domain"])
        auth.password = request["password"]
        auth.domain = request["domain"]
        auth.tls_cert_path = request["certificate_path"]
        auth.tls_key_path = request["private_key_path"]
        core.add_auth_info(auth)
        core.start()
        self.core = core
        self.emit("registration", state="progress")

    def command_start_monitoring(self, request: dict[str, Any]) -> None:
        if self.core is None:
            raise RuntimeError("not registered")
        if self.call is not None:
            raise RuntimeError("call already active")
        self._validate_monitoring(request)
        self.core.mic_enabled = False
        params = self.core.create_call_params(None)
        params.audio_enabled = True
        params.video_enabled = True
        params.audio_direction = linphone.MediaDirection.MediaDirectionSendRecv
        params.video_direction = linphone.MediaDirection.MediaDirectionRecvOnly
        params.media_encryption = linphone.MediaEncryption.MediaEncryptionSRTP
        params.mic_enabled = False
        params.add_custom_sdp_attribute("DEVADDR", request["device_address"])
        self.media_path = request.get("media_path")
        self.snapshot_path = request.get("snapshot_path")
        if self.media_path:
            media_fifo = Path(self.media_path)
            media_fifo.unlink(missing_ok=True)
            os.mkfifo(media_fifo, 0o600)
            # Keep both sides open so Linphone cannot block before PyAV attaches.
            self.media_guard_fd = os.open(media_fifo, os.O_RDWR | os.O_NONBLOCK)
            params.record_file = self.media_path
        target = self.core.create_address("sip:c100x@" + request["domain"])
        self.call = self.core.invite_address_with_params(target, params, None, None)
        if self.call is None:
            raise RuntimeError("invite failed")
        now = time.monotonic()
        self.setup_deadline = now + 15
        self.media_deadline = 0
        self.media_started = False
        callbacks = linphone.Factory.get().create_call_listener()
        callbacks.on_next_video_frame_decoded = self._next_video_frame_decoded
        self.call.add_listener(callbacks)
        self.call_callbacks = callbacks
        self.call.request_notify_next_video_frame_decoded()
        self.emit("call_state", state="connecting")

    @staticmethod
    def _validate_monitoring(request: dict[str, Any]) -> None:
        expected = {
            "target": "c100x",
            "video_direction": "recv_only",
            "audio_direction": "send_recv",
            "media_encryption": "srtp",
            "media_encryption_mandatory": True,
            "microphone_enabled": False,
            "setup_timeout": 15,
            "no_media_timeout": 10,
        }
        if any(request.get(key) != value for key, value in expected.items()):
            raise ValueError("invalid monitoring parameters")
        if not request.get("device_address"):
            raise ValueError("missing external unit address")

    def command_set_microphone(self, request: dict[str, Any]) -> None:
        enabled = bool(request["enabled"])
        if self.core is None or (enabled and not self.media_started):
            raise RuntimeError("microphone unavailable")
        self.core.mic_enabled = enabled
        self.microphone_enabled = enabled
        if not enabled:
            self.microphone_queue.clear()
        self.emit("microphone", enabled=enabled)

    def command_microphone_frame(self, request: dict[str, Any]) -> None:
        if not self.microphone_enabled or not self.media_started:
            raise RuntimeError("microphone disabled")
        pcm = base64.b64decode(request["pcm"], validate=True)
        if not pcm or len(pcm) > 19200 or len(pcm) % 2:
            raise ValueError("invalid PCM frame")
        self.microphone_queue.append(pcm)
        del self.microphone_queue[:-10]

    def command_end_session(self, _request: dict[str, Any]) -> None:
        self._end_call("requested")

    def command_snapshot(self, _request: dict[str, Any]) -> None:
        if self.call is None or not self.snapshot_path:
            raise RuntimeError("snapshot unavailable")
        if self.call.take_video_snapshot(self.snapshot_path) != 0:
            raise RuntimeError("snapshot failed")

    def command_send_strike(self, request: dict[str, Any]) -> None:
        if self.core is None:
            raise RuntimeError("not registered")
        room = self.core.get_chat_room_from_uri(request["recipient"])
        message = room.create_message_from_utf8(request["payload"])
        callbacks = linphone.Factory.get().create_chat_message_listener()
        callbacks.on_msg_state_changed = self._message_state_changed
        message.add_listener(callbacks)
        self.message_listener = callbacks
        self.message = message
        message.send()
        self.emit("message_delivery", state="in_progress")

    def command_shutdown(self, _request: dict[str, Any]) -> None:
        self._end_call("shutdown")
        self.shutdown_requested = True

    def _registration_changed(self, _core, _proxy, state, _message) -> None:
        names = {
            linphone.RegistrationState.RegistrationStateOk: "ok",
            linphone.RegistrationState.RegistrationStateProgress: "progress",
            linphone.RegistrationState.RegistrationStateCleared: "cleared",
            linphone.RegistrationState.RegistrationStateFailed: "failed",
        }
        self.emit("registration", state=names.get(state, "none"))

    def _call_state_changed(self, _core, call, state, _message) -> None:
        if state == linphone.CallState.CallStateIncomingReceived:
            remote = call.remote_address.as_string_uri_only().casefold()
            if not self.domain or f"c100x@{self.domain}".casefold() not in remote:
                self.core.decline_call(call, linphone.Reason.ReasonBusy)
                return
            self.emit("ring", call_id=call.call_log.call_id or "")
            self.incoming_call = call
            self.incoming_deadline = time.monotonic() + 2
            return
        names = {
            linphone.CallState.CallStateOutgoingInit: "outgoing_init",
            linphone.CallState.CallStateOutgoingProgress: "outgoing_progress",
            linphone.CallState.CallStateOutgoingRinging: "outgoing_ringing",
            linphone.CallState.CallStateConnected: "connected",
            linphone.CallState.CallStateStreamsRunning: "streams_running",
            linphone.CallState.CallStateEnd: "ended",
            linphone.CallState.CallStateError: "error",
            linphone.CallState.CallStateReleased: "released",
        }
        if name := names.get(state):
            self.emit("call_state", state=name)
        if state == linphone.CallState.CallStateStreamsRunning and call == self.call:
            self.media_started = True
            self.setup_deadline = 0
            self.media_deadline = time.monotonic() + 10
            if self.media_path:
                call.start_recording()
            params = call.current_params
            self.emit(
                "media_format",
                audio_direction="send_recv",
                video_direction="recv_only",
                encryption="srtp",
                video_enabled=bool(params.video_enabled),
                audio_enabled=bool(params.audio_enabled),
            )
        terminal_states = (
            linphone.CallState.CallStateEnd,
            linphone.CallState.CallStateError,
            linphone.CallState.CallStateReleased,
        )
        if state in terminal_states and call == self.call:
            self._clear_call()

    def _message_received(self, _core, _room, message) -> None:
        self.emit("message_received", call_id=message.call_id or "")

    def _next_video_frame_decoded(self, _call) -> None:
        if self.call is not None and self.snapshot_path:
            self.call.take_video_snapshot(self.snapshot_path)
        self.emit("first_frame", media_path=self.media_path)

    def _message_state_changed(self, message, state) -> None:
        names = {
            linphone.ChatMessageState.ChatMessageStateInProgress: "in_progress",
            linphone.ChatMessageState.ChatMessageStateDelivered: "delivered",
            linphone.ChatMessageState.ChatMessageStateNotDelivered: "not_delivered",
            linphone.ChatMessageState.ChatMessageStateFileTransferError: "error",
        }
        name = names.get(state)
        if name:
            self.emit("message_delivery", state=name)
        if state != linphone.ChatMessageState.ChatMessageStateInProgress:
            self.message = None
            self.message_listener = None

    def _watchdogs(self) -> None:
        now = time.monotonic()
        if self.incoming_call is not None and now >= self.incoming_deadline:
            self.core.decline_call(self.incoming_call, linphone.Reason.ReasonBusy)
            self.incoming_call = None
            self.incoming_deadline = 0
        if self.call is not None and self.media_started:
            audio = float(self.call.audio_stats.download_bandwidth)
            video = float(self.call.video_stats.download_bandwidth)
            if audio > 0 or video > 0:
                self.media_deadline = now + 10
            if now - self.last_bandwidth_emit >= 1:
                self.emit("bandwidth", audio_download=audio, video_download=video)
                self.last_bandwidth_emit = now
        if self.call is not None and self.setup_deadline and now >= self.setup_deadline:
            self.emit("error", code="setup_timeout")
            self._end_call("setup_timeout")
        elif self.call is not None and self.media_deadline and now >= self.media_deadline:
            self.emit("error", code="media_timeout")
            self._end_call("media_timeout")

    @staticmethod
    def _wav_header() -> bytes:
        # Streaming PCM: mono, signed 16-bit, 48 kHz, deliberately oversized data chunk.
        return b"RIFF" + struct.pack("<I", 0x7FFFFFFF) + b"WAVEfmt " + struct.pack(
            "<IHHIIHH", 16, 1, 1, 48000, 96000, 2, 16
        ) + b"data" + struct.pack("<I", 0x7FFFFFDB)

    def _pump_microphone(self) -> None:
        if self.microphone_fd is None:
            return
        frame = self.microphone_queue.pop(0) if self.microphone_queue else bytes(1920)
        with contextlib.suppress(BlockingIOError):
            os.write(self.microphone_fd, frame)

    def _end_call(self, reason: str) -> None:
        had_call = self.call is not None
        if self.core is not None:
            self.core.mic_enabled = False
        if self.call is not None:
            self.call.terminate()
        if had_call:
            self._clear_call()
            self.emit("call_state", state="idle", reason=reason)

    def _clear_call(self) -> None:
        self.call = None
        self.setup_deadline = 0
        self.media_deadline = 0
        self.media_started = False
        self.call_callbacks = None
        self.media_path = None
        if self.media_guard_fd is not None:
            os.close(self.media_guard_fd)
            self.media_guard_fd = None
        self.snapshot_path = None
        self.emit("microphone", enabled=False)

    def close(self) -> None:
        if self.core is not None:
            self.core.mic_enabled = False
            self.core.terminate_all_calls()
            self.core.stop()
        if self.microphone_fd is not None:
            os.close(self.microphone_fd)
            self.microphone_fd = None
        if self.media_guard_fd is not None:
            os.close(self.media_guard_fd)
            self.media_guard_fd = None
        for connection in (self.client, self.server):
            if connection is not None:
                with contextlib.suppress(OSError):
                    connection.close()
        self.socket_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", type=Path, required=True)
    arguments = parser.parse_args()
    runtime = Runtime(arguments.socket)
    signal.signal(signal.SIGTERM, lambda *_: setattr(runtime, "running", False))
    runtime.serve()


if __name__ == "__main__":
    main()
