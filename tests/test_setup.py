"""Home Assistant setup tests."""

from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bticino_c100x.const import (
    CONF_GATEWAY_ID,
    CONF_HOME_ID,
    CONF_LOCK_IDS,
    DOMAIN,
)


async def test_entry_creates_only_requested_entities(hass, enable_custom_integrations) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Front entrance",
        data={
            "username": "person@example.com",
            "password": "secret",
            CONF_HOME_ID: "home",
            CONF_GATEWAY_ID: "gateway",
            CONF_LOCK_IDS: ["door", "duplicate-door", "stale-door"],
        },
        unique_id="person@example.com",
    )
    entry.add_to_hass(hass)

    with patch("custom_components.bticino_c100x.C100XManager.async_start", new=AsyncMock()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get("lock.front_entrance_door") is not None
    assert len(hass.states.async_entity_ids("lock")) == 3
    assert hass.states.get("binary_sensor.front_entrance_ringing") is not None
    assert hass.states.get("event.front_entrance_doorbell") is not None
    assert hass.states.get("sensor.front_entrance_sip_registration") is not None
    assert not hass.states.async_entity_ids("light")

    with patch("custom_components.bticino_c100x.C100XManager.async_stop", new=AsyncMock()):
        assert await hass.config_entries.async_unload(entry.entry_id)
