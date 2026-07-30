"""Doorbell ringing binary sensor."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import C100XConfigEntry
from .entity import C100XEntity


async def async_setup_entry(entry_hass, entry: C100XConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(
        [C100XRingingSensor(entry), C100XSessionSensor(entry), C100XMicrophoneSensor(entry)]
    )


class C100XRingingSensor(C100XEntity, BinarySensorEntity):
    _attr_name = "Ringing"
    _attr_device_class = BinarySensorDeviceClass.SOUND

    def __init__(self, entry: C100XConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}-ringing"

    @property
    def is_on(self) -> bool:
        return self.manager.ringing


class C100XSessionSensor(C100XEntity, BinarySensorEntity):
    _attr_name = "Monitoring session"
    _attr_icon = "mdi:video-wireless"

    def __init__(self, entry: C100XConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}-monitoring-session"

    @property
    def is_on(self) -> bool:
        session = self.manager.media_session
        return bool(session and session.state in {"connecting", "streaming"})

    @property
    def extra_state_attributes(self) -> dict:
        session = self.manager.media_session
        return {
            "session_state": session.state if session else "unavailable",
            "last_error": self.manager.last_error,
        }


class C100XMicrophoneSensor(C100XEntity, BinarySensorEntity):
    _attr_name = "Microphone"
    _attr_icon = "mdi:microphone"

    def __init__(self, entry: C100XConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}-microphone"

    @property
    def is_on(self) -> bool:
        session = self.manager.media_session
        return bool(session and session.microphone_enabled)
