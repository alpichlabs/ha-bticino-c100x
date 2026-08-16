"""Classe 100X external-unit camera entities."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.camera import Camera, CameraEntityFeature, WebRTCAnswer
from homeassistant.components.camera.webrtc import (
    WebRTCClientConfiguration,
    WebRTCSendMessage,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from webrtc_models import RTCConfiguration, RTCIceCandidateInit, RTCIceServer

from . import C100XConfigEntry
from .entity import C100XEntity
from .media_session import SessionState
from .webrtc import WebRTCBridge
from .webrtc_config import STUN_URLS


async def async_setup_entry(
    entry_hass, entry: C100XConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(C100XCamera(entry, camera_id) for camera_id in entry.runtime_data.manager.camera_ids)


class C100XCamera(C100XEntity, Camera):
    """A user-started monitoring view with a passive cached snapshot."""

    _attr_name = "Front door"
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(self, entry: C100XConfigEntry, camera_id: str) -> None:
        C100XEntity.__init__(self, entry)
        Camera.__init__(self)
        self._camera_id = camera_id
        self._attr_unique_id = f"{entry.entry_id}-{camera_id}-camera"
        self._bridge = WebRTCBridge(
            Path(self.manager._material_dir, "playback.sdp"),
            self._viewer_changed,
            lambda: self.manager.media_session.runtime.audio_track
            if self.manager.media_session
            else None,
            Path(self.manager._material_dir, "snapshot.jpg"),
        )

    async def async_camera_image(self, width=None, height=None) -> bytes | None:
        """Return only a cached frame; snapshots must never initiate a SIP call."""
        path = Path(self.manager._material_dir, "snapshot.jpg")
        if not path.is_file():
            return None
        return await self.hass.async_add_executor_job(path.read_bytes)

    @property
    def is_streaming(self) -> bool:
        session = self.manager.media_session
        return bool(
            session
            and session.state == SessionState.STREAMING
            and session.device_address == self._camera_id
        )

    def _async_get_webrtc_client_configuration(self) -> WebRTCClientConfiguration:
        """Give remote browsers a server-reflexive ICE candidate."""
        return WebRTCClientConfiguration(
            configuration=RTCConfiguration(
                ice_servers=[RTCIceServer(urls=list(STUN_URLS))]
            )
        )

    async def async_handle_async_webrtc_offer(
        self, offer_sdp: str, session_id: str, send_message: WebRTCSendMessage
    ) -> None:
        """Attach the player only to an explicitly started monitoring session."""
        session = self.manager.media_session
        if (
            session is None
            or session.device_address != self._camera_id
            or session.state not in {SessionState.CONNECTING, SessionState.STREAMING}
        ):
            raise RuntimeError("Monitoring session is not active")

        self._bridge.prepare(session_id)
        try:
            answer = await self._bridge.answer(session_id, offer_sdp)
            send_message(WebRTCAnswer(answer=answer))
        except Exception:
            await self._bridge.close(session_id)
            raise

    async def async_on_webrtc_candidate(
        self, session_id: str, candidate: RTCIceCandidateInit
    ) -> None:
        await self._bridge.add_candidate(session_id, candidate)

    def close_webrtc_session(self, session_id: str) -> None:
        self.hass.async_create_task(self._bridge.close(session_id))

    def _viewer_changed(self, change: int) -> None:
        session = self.manager.media_session
        if not session:
            return
        if change > 0:
            session.add_viewer()
        else:
            session.remove_viewer()
