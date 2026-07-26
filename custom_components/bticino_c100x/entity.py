"""Shared Home Assistant entity base."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from . import C100XConfigEntry
from .const import DOMAIN
from .manager import C100XManager


class C100XEntity(Entity):
    _attr_has_entity_name = True

    def __init__(self, entry: C100XConfigEntry) -> None:
        self.entry = entry
        self.manager: C100XManager = entry.runtime_data.manager
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data["gateway_id"])},
            manufacturer="BTicino",
            model="Classe 100X (firmware 1.x)",
            name=entry.title,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.manager.add_listener(self.async_write_ha_state))

