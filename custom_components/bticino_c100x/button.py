"""Momentary door-release button entities."""

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import C100XConfigEntry
from .const import CONF_LOCK_IDS
from .entity import C100XEntity


async def async_setup_entry(entry_hass, entry: C100XConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    lock_ids = entry.options.get(CONF_LOCK_IDS, entry.data[CONF_LOCK_IDS])
    selected_unique_ids = {f"{entry.entry_id}-{lock_id}" for lock_id in lock_ids}
    registry = er.async_get(entry_hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.domain == "lock" or (entity.domain == "button" and entity.unique_id not in selected_unique_ids):
            registry.async_remove(entity.entity_id)
    async_add_entities(C100XReleaseButton(entry, lock_id) for lock_id in lock_ids)


class C100XReleaseButton(C100XEntity, ButtonEntity):
    """Pulse an electric strike for its configured release interval."""

    _attr_name = "Release door"
    _attr_icon = "mdi:door-open"

    def __init__(self, entry: C100XConfigEntry, lock_id: str) -> None:
        super().__init__(entry)
        self._lock_id = lock_id
        self._attr_unique_id = f"{entry.entry_id}-{lock_id}"

    async def async_press(self) -> None:
        await self.manager.async_release(self._lock_id)
