"""Local WebRTC fan-out for decoded Linphone call media."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer, MediaRelay
from aiortc.sdp import candidate_from_sdp


class WebRTCBridge:
    """Share one growing Linphone recording between WebRTC viewers."""

    def __init__(self, media_path: Path, viewer_changed) -> None:
        self.media_path = media_path
        self.viewer_changed = viewer_changed
        self._player: MediaPlayer | None = None
        self._relay = MediaRelay()
        self._peers: dict[str, RTCPeerConnection] = {}
        self._lock = asyncio.Lock()

    async def answer(self, session_id: str, offer_sdp: str) -> str:
        async with self._lock:
            await self._ensure_player()
            peer = RTCPeerConnection()
            self._peers[session_id] = peer
            self.viewer_changed(1)

            @peer.on("connectionstatechange")
            async def connection_state_changed() -> None:
                if peer.connectionState in {"failed", "closed", "disconnected"}:
                    await self.close(session_id)

            await peer.setRemoteDescription(RTCSessionDescription(sdp=offer_sdp, type="offer"))
            assert self._player
            if self._player.video:
                peer.addTrack(self._relay.subscribe(self._player.video, buffered=False))
            if self._player.audio:
                peer.addTrack(self._relay.subscribe(self._player.audio, buffered=False))
            answer = await peer.createAnswer()
            await peer.setLocalDescription(answer)
            assert peer.localDescription
            return peer.localDescription.sdp

    async def add_candidate(self, session_id: str, value: Any) -> None:
        peer = self._peers.get(session_id)
        if peer is None:
            return
        raw = getattr(value, "candidate", None)
        if not raw:
            await peer.addIceCandidate(None)
            return
        candidate = candidate_from_sdp(raw.removeprefix("candidate:"))
        candidate.sdpMid = getattr(value, "sdp_mid", None)
        candidate.sdpMLineIndex = getattr(value, "sdp_m_line_index", None)
        await peer.addIceCandidate(candidate)

    async def close(self, session_id: str) -> None:
        async with self._lock:
            peer = self._peers.pop(session_id, None)
            if peer is None:
                return
            await peer.close()
            self.viewer_changed(-1)
            if not self._peers:
                self._player = None

    async def close_all(self) -> None:
        for session_id in tuple(self._peers):
            await self.close(session_id)

    async def _ensure_player(self) -> None:
        if self._player is not None:
            return
        for _ in range(100):
            if self.media_path.is_file() and self.media_path.stat().st_size:
                self._player = MediaPlayer(str(self.media_path), format="matroska")
                return
            await asyncio.sleep(0.1)
        raise RuntimeError("Linphone media channel did not become ready")
