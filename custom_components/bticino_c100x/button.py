"""Momentary door-release button entities."""

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import C100XConfigEntry
from .entity import C100XEntity


async def async_setup_entry(entry_hass, entry: C100XConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    lock_ids = entry.runtime_data.manager.lock_ids
    staircase_modules = entry.runtime_data.manager.staircase_modules
    selected_unique_ids = {f"{entry.entry_id}-{lock_id}" for lock_id in lock_ids}
    selected_unique_ids.update(
        f"{entry.entry_id}-{module['id']}-staircase"
        for module in staircase_modules
    )
    for camera_id in entry.runtime_data.manager.camera_ids:
        selected_unique_ids.update(
            {f"{entry.entry_id}-{camera_id}-start", f"{entry.entry_id}-{camera_id}-end"}
        )
    registry = er.async_get(entry_hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.domain == "lock" or (entity.domain == "button" and entity.unique_id not in selected_unique_ids):
            registry.async_remove(entity.entity_id)
    entities = [C100XReleaseButton(entry, lock_id) for lock_id in lock_ids]
    entities.extend(
        C100XStaircaseButton(
            entry,
            str(module["id"]),
            str(module.get("name") or "Staircase action"),
        )
        for module in staircase_modules
    )
    for camera_id in entry.runtime_data.manager.camera_ids:
        entities.extend((C100XStartButton(entry, camera_id), C100XEndButton(entry, camera_id)))
    async_add_entities(entities)


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


class C100XStaircaseButton(C100XEntity, ButtonEntity):
    """Activate one configured staircase actuator."""

    _attr_icon = "mdi:stairs"

    def __init__(
        self, entry: C100XConfigEntry, module_id: str, name: str
    ) -> None:
        super().__init__(entry)
        self._module_id = module_id
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}-{module_id}-staircase"

    async def async_press(self) -> None:
        await self.manager.async_activate_staircase(self._module_id)


class C100XStartButton(C100XEntity, ButtonEntity):
    """Start one explicit, receive-only monitoring session."""

    _attr_name = "Start monitoring"
    _attr_icon = "mdi:video"

    def __init__(self, entry: C100XConfigEntry, camera_id: str) -> None:
        super().__init__(entry)
        self._camera_id = camera_id
        self._attr_unique_id = f"{entry.entry_id}-{camera_id}-start"

    async def async_press(self) -> None:
        await self.manager.async_start_monitoring(self._camera_id)


class C100XEndButton(C100XEntity, ButtonEntity):
    """End the shared monitoring session."""

    _attr_name = "End session"
    _attr_icon = "mdi:phone-hangup"

    def __init__(self, entry: C100XConfigEntry, camera_id: str) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}-{camera_id}-end"

    async def async_press(self) -> None:
        await self.manager.async_end_monitoring()
