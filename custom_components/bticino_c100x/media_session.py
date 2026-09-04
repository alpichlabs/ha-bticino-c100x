"""User-initiated Classe 100X monitoring session state."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from enum import StrEnum

from .media_runtime import MediaRuntime


class SessionState(StrEnum):
    IDLE = "idle"
    CONNECTING = "connecting"
    STREAMING = "streaming"
    ENDING = "ending"
    ERROR = "error"


class MediaSession:
    """Serialize monitoring and microphone transitions for one gateway."""

    def __init__(
        self,
        runtime: MediaRuntime,
        notify: Callable[[], None],
        domain: str = "",
        media_path=None,
        snapshot_path=None,
    ) -> None:
        self.runtime = runtime
        self.notify = notify
        self.state = SessionState.IDLE
        self.device_address: str | None = None
        self.microphone_enabled = False
        self.viewer_count = 0
        self.last_error: str | None = None
        self.latest_jpeg: bytes | None = None
        self.domain = domain
        self.media_path = media_path
        self.snapshot_path = snapshot_path
        self._lock = asyncio.Lock()
        self._ready_event: asyncio.Event = asyncio.Event()

    async def start(self, device_address: str) -> asyncio.Event:
        """Start monitoring and return an Event that fires when STREAMING."""
        async with self._lock:
            if self.state in {SessionState.CONNECTING, SessionState.STREAMING}:
                if self.device_address == device_address:
                    self._ready_event.set()
                    return self._ready_event
                await self._end_locked()
            self.microphone_enabled = False
            self.device_address = device_address
            self.last_error = None
            self.state = SessionState.CONNECTING
            self._ready_event.clear()
            self.notify()
            try:
                await self.runtime.set_microphone(False)
                await self.runtime.start_monitoring(
                    device_address,
                    self.domain,
                    self.media_path,
                    self.snapshot_path,
                )
            except Exception as err:
                self.state = SessionState.ERROR
                self.microphone_enabled = False
                self.last_error = type(err).__name__
                self._ready_event.set()
                self.notify()
                raise
            return self._ready_event

    async def end(self) -> None:
        async with self._lock:
            await self._end_locked()

    async def set_microphone(self, enabled: bool) -> None:
        async with self._lock:
            if enabled and self.state != SessionState.STREAMING:
                raise RuntimeError("Microphone requires an active media session")
            await self.runtime.set_microphone(enabled)
            self.microphone_enabled = enabled
            self.notify()

    def handle_event(self, event: dict) -> None:
        event_type = event.get("event")
        if event_type == "call_state" and event.get("state") == "streams_running":
            self.state = SessionState.STREAMING
            self._ready_event.set()
        elif event_type == "call_state" and event.get("state") == "error":
            self.state = SessionState.ERROR
            self.microphone_enabled = False
            self.last_error = "call_error"
        elif event_type == "call_state" and event.get("state") in {"idle", "ended", "released"}:
            if self.state != SessionState.ERROR:
                self.state = SessionState.IDLE
                self.device_address = None
                self.microphone_enabled = False
        elif event_type == "error":
            self.state = SessionState.ERROR
            self.microphone_enabled = False
            self.last_error = str(event.get("code") or "runtime_error")
        elif event_type == "snapshot" and isinstance(event.get("jpeg"), bytes):
            self.latest_jpeg = event["jpeg"]
        self.notify()

    def add_viewer(self) -> None:
        """Track a WebRTC viewer without taking ownership of the SIP call."""
        self.viewer_count += 1
        self.notify()

    def remove_viewer(self) -> None:
        """Drop a WebRTC viewer without ending user-started monitoring."""
        self.viewer_count = max(0, self.viewer_count - 1)
        self.notify()

    async def switch_camera(self, camera_id: str) -> None:
        """Switch to a different camera via re-INVITE without tearing down.

        The SIP dialog, RTP ports, and FFmpeg process stay alive.
        Only the DEVADDR attribute changes.
        """
        async with self._lock:
            if self.state != SessionState.STREAMING:
                raise RuntimeError("Camera switch requires an active streaming session")
            if self.device_address == camera_id:
                return
            self.last_error = None
            self.state = SessionState.CONNECTING
            self.notify()
            try:
                new_session = await self.runtime.switch_camera(camera_id)
                self.device_address = camera_id
                self.state = SessionState.STREAMING
            except Exception as err:
                self.state = SessionState.ERROR
                self.last_error = type(err).__name__
                self.notify()
                raise

    async def _end_locked(self) -> None:
        if self.state == SessionState.IDLE:
            self.microphone_enabled = False
            return
        self.state = SessionState.ENDING
        self.notify()
        try:
            # Match the safety invariant used by the official app: disable
            # capture before the call object is released.
            await self.runtime.set_microphone(False)
            self.microphone_enabled = False
            await self.runtime.end_session()
        finally:
            self.state = SessionState.IDLE
            self.device_address = None
            self.microphone_enabled = False
            self.notify()
