"""Door-release lock entities."""

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import C100XConfigEntry
from .const import CONF_LOCK_IDS
from .entity import C100XEntity


async def async_setup_entry(entry_hass, entry: C100XConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    lock_ids = entry.data[CONF_LOCK_IDS]
    # Classe 100X exposes one physical door release. Some Legrand plants
    # nevertheless return duplicate/stale lock modules for the same gateway;
    # only the primary module should become an actionable Home Assistant entity.
    async_add_entities([C100XLock(entry, lock_ids[0])] if lock_ids else [])


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

    @property
    def available(self) -> bool:
        return self.manager.registered

    async def async_unlock(self, **kwargs: Any) -> None:
        await self.manager.async_open(self._lock_id)
