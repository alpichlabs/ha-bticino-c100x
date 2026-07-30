"""Diagnostic sensors."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import C100XConfigEntry
from .entity import C100XEntity


async def async_setup_entry(entry_hass, entry: C100XConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(
        [
            C100XRegistrationSensor(entry),
            C100XCertificateSensor(entry),
            C100XLastRingSensor(entry),
            C100XLastMediaErrorSensor(entry),
        ]
    )


class C100XDiagnosticSensor(C100XEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC


class C100XRegistrationSensor(C100XDiagnosticSensor):
    _attr_name = "SIP registration"

    def __init__(self, entry: C100XConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}-sip-registration"

    @property
    def native_value(self) -> str:
        return "registered" if self.manager.registered else "disconnected"


class C100XCertificateSensor(C100XDiagnosticSensor):
    _attr_name = "SIP certificate expiry"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, entry: C100XConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}-certificate-expiry"

    @property
    def native_value(self):
        return self.manager.certificate_expires_at


class C100XLastRingSensor(C100XDiagnosticSensor):
    _attr_name = "Last ring"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, entry: C100XConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}-last-ring"

    @property
    def native_value(self):
        return self.manager.last_ring


class C100XLastMediaErrorSensor(C100XDiagnosticSensor):
    _attr_name = "Last media error"
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, entry: C100XConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}-last-media-error"

    @property
    def native_value(self):
        return self.manager.last_error
