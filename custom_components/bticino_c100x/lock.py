"""Door-release lock entities."""

from typing import Any

from homeassistant.components.lock import LockEntity
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
        if entity.domain == "lock" and entity.unique_id not in selected_unique_ids:
            registry.async_remove(entity.entity_id)
    async_add_entities(C100XLock(entry, lock_id) for lock_id in lock_ids)


class C100XLock(C100XEntity, LockEntity):
    """Momentary door release represented through Home Assistant's unlock action."""

    _attr_name = "Door"

    def __init__(self, entry: C100XConfigEntry, lock_id: str) -> None:
        super().__init__(entry)
        self._lock_id = lock_id
        self._attr_unique_id = f"{entry.entry_id}-{lock_id}"

    @property
    def is_locked(self) -> bool:
        return True

    async def async_unlock(self, **kwargs: Any) -> None:
        await self.manager.async_open(self._lock_id)
