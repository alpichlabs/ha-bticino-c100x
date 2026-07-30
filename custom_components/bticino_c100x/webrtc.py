"""Local WebRTC fan-out for decoded Classe 100X call media."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any

from aiortc import (
    MediaStreamTrack,
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)
from aiortc.contrib.media import MediaPlayer, MediaRelay
from aiortc.sdp import candidate_from_sdp

_LOGGER = logging.getLogger(__name__)


class _SnapshotTrack(MediaStreamTrack):
    """Cache an occasional decoded frame without adding queue latency."""

    kind = "video"

    def __init__(self, source: MediaStreamTrack, path: Path) -> None:
        super().__init__()
        self.source = source
        self.path = path
        self._last_snapshot = 0.0
        self._snapshot_task: asyncio.Task | None = None

    async def recv(self):
        frame = await self.source.recv()
        now = time.monotonic()
        if now - self._last_snapshot >= 2 and (
            self._snapshot_task is None or self._snapshot_task.done()
        ):
            self._last_snapshot = now
            self._snapshot_task = asyncio.create_task(
                asyncio.to_thread(_save_snapshot, frame, self.path)
            )
        return frame


def _save_snapshot(frame, path: Path) -> None:
    temporary = path.with_suffix(".tmp.jpg")
    frame.to_image().save(temporary, format="JPEG", quality=85)
    temporary.chmod(0o600)
    temporary.replace(path)


class WebRTCBridge:
    """Share one bounded local media channel between WebRTC viewers."""

    def __init__(
        self, media_path: Path, viewer_changed, audio_track=None, snapshot_path: Path | None = None
    ) -> None:
        self.media_path = media_path
        self.viewer_changed = viewer_changed
        self.audio_track = audio_track
        self.snapshot_path = snapshot_path
        self._player: MediaPlayer | None = None
        self._video_source: MediaStreamTrack | None = None
        self._relay = MediaRelay()
        self._peers: dict[str, RTCPeerConnection] = {}
        self._pending_candidates: dict[str, list[Any]] = {}
        self._lock = asyncio.Lock()

    def prepare(self, session_id: str) -> None:
        """Register a browser session before the slower SIP setup begins."""
        self._pending_candidates.setdefault(session_id, [])

    async def answer(self, session_id: str, offer_sdp: str) -> str:
        async with self._lock:
            await self._ensure_player()
            peer = RTCPeerConnection(
                RTCConfiguration(
                    iceServers=[RTCIceServer(urls="stun:stun.linphone.org:3478")]
                )
            )
            self._peers[session_id] = peer
            self.viewer_changed(1)

            @peer.on("connectionstatechange")
            async def connection_state_changed() -> None:
                _LOGGER.warning(
                    "BTicino WebRTC connection state: %s", peer.connectionState
                )
                if peer.connectionState in {"failed", "closed", "disconnected"}:
                    await self.close(session_id)

            @peer.on("iceconnectionstatechange")
            async def ice_connection_state_changed() -> None:
                _LOGGER.warning(
                    "BTicino WebRTC ICE state: %s", peer.iceConnectionState
                )

            try:
                await peer.setRemoteDescription(
                    RTCSessionDescription(sdp=offer_sdp, type="offer")
                )
                pending = self._pending_candidates.pop(session_id, [])
                for candidate in pending:
                    await self._apply_candidate(peer, candidate)
                _LOGGER.warning(
                    "BTicino WebRTC browser offer: %s", _candidate_summary(offer_sdp)
                )
                assert self._player
                if self._video_source:
                    peer.addTrack(self._relay.subscribe(self._video_source, buffered=False))
                if self._player.audio:
                    peer.addTrack(self._relay.subscribe(self._player.audio, buffered=False))
                elif self.audio_track and (track := self.audio_track()):
                    peer.addTrack(self._relay.subscribe(track, buffered=False))
                answer = await peer.createAnswer()
                await peer.setLocalDescription(answer)
                assert peer.localDescription
                _LOGGER.warning(
                    "BTicino WebRTC server answer: %s",
                    _candidate_summary(peer.localDescription.sdp),
                )
                return peer.localDescription.sdp
            except Exception:
                self._peers.pop(session_id, None)
                self._pending_candidates.pop(session_id, None)
                self.viewer_changed(-1)
                await peer.close()
                raise

    async def add_candidate(self, session_id: str, value: Any) -> None:
        peer = self._peers.get(session_id)
        if session_id not in self._pending_candidates and peer is None:
            _LOGGER.warning("BTicino WebRTC candidate ignored: unknown session")
            return
        if peer is None or peer.remoteDescription is None:
            pending = self._pending_candidates.setdefault(session_id, [])
            if len(pending) < 64:
                pending.append(value)
            else:
                _LOGGER.warning("BTicino WebRTC candidate queue is full")
            return
        await self._apply_candidate(peer, value)

    async def _apply_candidate(self, peer: RTCPeerConnection, value: Any) -> None:
        """Apply one browser ICE candidate after the offer is installed."""
        raw = getattr(value, "candidate", None)
        if not raw:
            _LOGGER.warning("BTicino WebRTC browser candidates complete")
            await peer.addIceCandidate(None)
            return
        match = re.search(r"\styp\s+(\w+)", raw)
        _LOGGER.warning(
            "BTicino WebRTC browser candidate: %s",
            match.group(1) if match else "unknown",
        )
        candidate = candidate_from_sdp(raw.removeprefix("candidate:"))
        candidate.sdpMid = getattr(value, "sdp_mid", None)
        candidate.sdpMLineIndex = getattr(value, "sdp_m_line_index", None)
        await peer.addIceCandidate(candidate)

    async def close(self, session_id: str) -> None:
        async with self._lock:
            self._pending_candidates.pop(session_id, None)
            peer = self._peers.pop(session_id, None)
            if peer is None:
                return
            await peer.close()
            self.viewer_changed(-1)
            if not self._peers:
                if self._player:
                    if self._player.video:
                        self._player.video.stop()
                    if self._player.audio:
                        self._player.audio.stop()
                self._player = None
                self._video_source = None

    async def close_all(self) -> None:
        for session_id in tuple(self._peers):
            await self.close(session_id)

    async def _ensure_player(self) -> None:
        if self._player is not None:
            return
        for _ in range(100):
            if self.media_path.exists():
                self._player = await asyncio.to_thread(
                    MediaPlayer,
                    str(self.media_path),
                    format="sdp",
                    options={
                        "protocol_whitelist": "file,udp,rtp",
                        "analyzeduration": "0",
                        "probesize": "32",
                    },
                )
                self._video_source = self._player.video
                if self._video_source and self.snapshot_path:
                    self._video_source = _SnapshotTrack(
                        self._video_source, self.snapshot_path
                    )
                return
            await asyncio.sleep(0.1)
        raise RuntimeError("Media channel did not become ready")


def _candidate_summary(sdp: str) -> str:
    """Describe ICE candidates without logging addresses or credentials."""
    types = re.findall(r"^a=candidate:.*?\styp\s+(\w+)", sdp, re.MULTILINE)
    media = re.findall(r"^m=(\w+)", sdp, re.MULTILINE)
    return f"media={','.join(media) or 'none'} candidates={','.join(types) or 'none'}"
