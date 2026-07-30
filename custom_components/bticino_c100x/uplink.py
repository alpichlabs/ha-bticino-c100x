"""Explicit, single-owner browser microphone uplink."""

from __future__ import annotations

import asyncio
from typing import Any

from aiortc import RTCPeerConnection, RTCSessionDescription
from av.audio.resampler import AudioResampler

from .media_session import MediaSession


class MicrophoneUplink:
    """Receive browser audio and forward bounded PCM frames to SRTP."""

    def __init__(self, session: MediaSession) -> None:
        self.session = session
        self.owner: str | None = None
        self.peer: RTCPeerConnection | None = None
        self._task: asyncio.Task[None] | None = None
        self._track_ready = asyncio.Event()
        self._lock = asyncio.Lock()

    async def negotiate(self, owner: str, offer_sdp: str) -> str:
        async with self._lock:
            if self.owner and self.owner != owner:
                raise RuntimeError("Microphone is already in use")
            await self._close_locked()
            self.owner = owner
            self._track_ready.clear()
            peer = RTCPeerConnection()
            self.peer = peer

            @peer.on("track")
            def track_received(track) -> None:
                if track.kind != "audio" or self._task:
                    return
                self._track_ready.set()
                self._task = asyncio.create_task(self._forward(track))

            @peer.on("connectionstatechange")
            async def state_changed() -> None:
                if peer.connectionState in {"failed", "closed", "disconnected"}:
                    await self.close(owner)

            await peer.setRemoteDescription(RTCSessionDescription(sdp=offer_sdp, type="offer"))
            answer = await peer.createAnswer()
            await peer.setLocalDescription(answer)
            try:
                await asyncio.wait_for(self._track_ready.wait(), timeout=10)
            except TimeoutError:
                await self._close_locked()
                raise RuntimeError("Microphone uplink has no audio track") from None
            # Enable SRTP transmission only after the browser track exists.
            await self.session.set_microphone(True)
            assert peer.localDescription
            return peer.localDescription.sdp

    async def close(self, owner: str | None = None) -> None:
        async with self._lock:
            if owner is not None and self.owner != owner:
                raise RuntimeError("Microphone is owned by another client")
            await self._close_locked()

    async def _close_locked(self) -> None:
        # Safety ordering is intentional: mute RTP before stopping capture.
        if self.session.microphone_enabled:
            await self.session.set_microphone(False)
        task, self._task = self._task, None
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        peer, self.peer = self.peer, None
        if peer:
            await peer.close()
        self.owner = None
        self._track_ready.clear()

    async def _forward(self, track: Any) -> None:
        resampler = AudioResampler(format="s16", layout="mono", rate=8000)
        while True:
            frame = await track.recv()
            for converted in resampler.resample(frame):
                pcm = bytes(converted.planes[0])[: converted.samples * 2]
                await self.session.runtime.send_microphone_frame(pcm)
