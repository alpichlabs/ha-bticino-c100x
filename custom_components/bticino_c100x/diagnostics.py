"""Redacted diagnostics."""

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import C100XConfigEntry

REDACT = {"password", "username", "home_id", "gateway_id", "lock_ids"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: C100XConfigEntry) -> dict:
    manager = entry.runtime_data.manager
    return {
        "entry": async_redact_data(dict(entry.data), REDACT),
        "sip_registered": manager.registered,
        "certificate_expires_at": manager.certificate_expires_at,
        "last_ring": manager.last_ring,
        "last_error_type": manager.last_error,
    }

