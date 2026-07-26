"""Runtime manager tests."""

from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bticino_c100x.const import CONF_GATEWAY_ID, CONF_HOME_ID, DOMAIN, EVENT_RING
from custom_components.bticino_c100x.manager import C100XManager


async def test_ring_is_deduplicated_and_fired_on_bus(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_GATEWAY_ID: "gateway", CONF_HOME_ID: "home"},
        unique_id="account",
    )
    entry.add_to_hass(hass)
    manager = C100XManager(hass, entry, AsyncMock(), AsyncMock())
    entity_events: list[dict] = []
    bus_events = []
    manager.add_ring_listener(entity_events.append)
    hass.bus.async_listen(EVENT_RING, bus_events.append)

    await manager._async_ring({"call_id": "call-1", "from": "sensitive-sip-uri"})
    await manager._async_ring({"call_id": "call-1", "from": "sensitive-sip-uri"})
    await hass.async_block_till_done()

    assert entity_events == [{"call_id": "call-1"}]
    assert len(bus_events) == 1
    assert bus_events[0].data == {CONF_GATEWAY_ID: "gateway", "call_id": "call-1"}
    manager._clear_ring()


async def test_open_uses_cloud_command_even_when_sip_is_disconnected(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_GATEWAY_ID: "gateway", CONF_HOME_ID: "home"},
        unique_id="account",
    )
    entry.add_to_hass(hass)
    api = AsyncMock()
    manager = C100XManager(hass, entry, AsyncMock(), api)

    await manager.async_open("lock-module")

    api.open_lock.assert_awaited_once_with("gateway", "lock-module")
