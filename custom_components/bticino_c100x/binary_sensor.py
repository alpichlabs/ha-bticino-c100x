"""Doorbell ringing binary sensor."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import C100XConfigEntry
from .entity import C100XEntity


async def async_setup_entry(entry_hass, entry: C100XConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([C100XRingingSensor(entry)])


class C100XRingingSensor(C100XEntity, BinarySensorEntity):
    _attr_name = "Ringing"
    _attr_device_class = BinarySensorDeviceClass.SOUND

    def __init__(self, entry: C100XConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}-ringing"

    @property
    def is_on(self) -> bool:
        return self.manager.ringing

