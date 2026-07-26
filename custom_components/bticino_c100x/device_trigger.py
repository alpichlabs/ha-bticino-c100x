"""Device automation triggers for BTicino C100X."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_EVENT, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import CONF_GATEWAY_ID, DOMAIN, EVENT_RING

TRIGGER_TYPE_RING = "ring"
TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend({vol.Required(CONF_TYPE): vol.In([TRIGGER_TYPE_RING])})


async def async_get_triggers(hass: HomeAssistant, device_id: str) -> list[dict[str, Any]]:
    """Return the ring trigger for integration devices."""
    device = dr.async_get(hass).async_get(device_id)
    if not device or not any(
        (entry := hass.config_entries.async_get_entry(entry_id)) and entry.domain == DOMAIN
        for entry_id in device.config_entries
    ):
        return []
    return [
        {
            CONF_PLATFORM: "device",
            CONF_DEVICE_ID: device_id,
            CONF_DOMAIN: DOMAIN,
            CONF_TYPE: TRIGGER_TYPE_RING,
        }
    ]


async def async_validate_trigger_config(hass: HomeAssistant, config: ConfigType) -> ConfigType:
    """Validate a ring trigger."""
    return TRIGGER_SCHEMA(config)


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Attach a ring event trigger for one gateway."""
    device = dr.async_get(hass).async_get(config[CONF_DEVICE_ID])
    if device is None:
        raise ValueError(f"Unknown device {config[CONF_DEVICE_ID]}")
    entry = next(
        (
            candidate
            for entry_id in device.config_entries
            if (candidate := hass.config_entries.async_get_entry(entry_id)) and candidate.domain == DOMAIN
        ),
        None,
    )
    if entry is None:
        raise ValueError("Device has no BTicino C100X config entry")
    return await event_trigger.async_attach_trigger(
        hass,
        event_trigger.TRIGGER_SCHEMA(
            {
                event_trigger.CONF_PLATFORM: CONF_EVENT,
                event_trigger.CONF_EVENT_TYPE: EVENT_RING,
                event_trigger.CONF_EVENT_DATA: {CONF_GATEWAY_ID: entry.data[CONF_GATEWAY_ID]},
            }
        ),
        action,
        trigger_info,
        platform_type="device",
    )

