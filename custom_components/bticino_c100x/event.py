"""Doorbell event entity."""

from homeassistant.components.event import EventEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import C100XConfigEntry
from .entity import C100XEntity


async def async_setup_entry(entry_hass, entry: C100XConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([C100XDoorbellEvent(entry)])


class C100XDoorbellEvent(C100XEntity, EventEntity):
    _attr_name = "Doorbell"
    _attr_event_types = ("ring",)

    def __init__(self, entry: C100XConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}-doorbell"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.manager.add_ring_listener(self._handle_ring))

    def _handle_ring(self, event: dict) -> None:
        self._trigger_event("ring", event)
        self.async_write_ha_state()
