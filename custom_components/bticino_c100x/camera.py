"""Classe 100X external-unit camera entities."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components.camera import Camera, CameraEntityFeature, WebRTCAnswer
from homeassistant.components.camera.webrtc import (
    WebRTCClientConfiguration,
    WebRTCSendMessage,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from webrtc_models import RTCConfiguration, RTCIceCandidateInit, RTCIceServer

from . import DOMAIN, C100XConfigEntry
from .entity import C100XEntity
from .media_session import SessionState
from .webrtc import WebRTCBridge
from .webrtc_config import STUN_URLS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    entry_hass, entry: C100XConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        C100XCamera(entry, camera_id) for camera_id in entry.runtime_data.manager.camera_ids
    )


class C100XCamera(C100XEntity, Camera):
    """A user-started monitoring view with a passive cached snapshot."""

    _attr_name: str = "Front door"
    _attr_supported_features: CameraEntityFeature = CameraEntityFeature.STREAM

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

        # Track which camera is currently active for this camera entity
        self._active_camera: str | None = None
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data["gateway_id"], f"camera-{camera_id}")},
            "name": f"Camera {camera_id}",
            "manufacturer": "BTicino",
            "model": "Classe 100X External Unit",
            "via_device": (DOMAIN, entry.data["gateway_id"]),
        }

        # Register as camera switch listener
        self._attr_extra_state_attributes: dict[str, Any] = {
            "camera_id": camera_id,
            "active": False,
        }

    @callback
    def _async_update_camera_state(self) -> None:
        """Update camera attributes based on session state."""
        session = self.manager.media_session
        is_active = (
            session is not None
            and session.state == SessionState.STREAMING
            and session.device_address == self._camera_id
        )

        if is_active and self._active_camera != self._camera_id:
            self._active_camera = self._camera_id
            self._attr_name = f"Camera {self._camera_id}"
            self._attr_extra_state_attributes["active"] = True
        elif not is_active and self._active_camera == self._camera_id:
            self._active_camera = None
            self._attr_name = f"Camera {self._camera_id}"
            self._attr_extra_state_attributes["active"] = False

        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register state change listener."""
        await super().async_added_to_hass()
        self.async_on_remove(self.manager.add_listener(self._async_update_camera_state))

    async def async_camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
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

    async def async_switch_camera(self, camera_id: str) -> None:
        """Switch to a different camera via re-INVITE without tearing down."""
        if self.manager.media_session is None:
            raise RuntimeError("No active media session")

        await self.manager.media_session.switch_camera(camera_id)
