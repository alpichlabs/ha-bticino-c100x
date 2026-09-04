"""Authenticated session-control WebSocket API."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .const import DOMAIN


def async_register(hass: HomeAssistant) -> None:
    for command in (ws_status, ws_start, ws_end, ws_microphone_negotiate, ws_microphone_set):
        websocket_api.async_register_command(hass, command)


def _manager(hass: HomeAssistant, entry_id: str):
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN or not getattr(entry, "runtime_data", None):
        raise ValueError("Unknown BTicino C100X entry")
    return entry.runtime_data.manager


BASE = {
    vol.Required("type"): str,
    vol.Required("entry_id"): str,
}


@websocket_api.websocket_command({**BASE, vol.Required("type"): f"{DOMAIN}/status"})
@websocket_api.async_response
async def ws_status(hass, connection, msg) -> None:
    try:
        manager = _manager(hass, msg["entry_id"])
    except ValueError as error:
        connection.send_error(msg["id"], "not_found", str(error))
        return
    session = manager.media_session
    connection.send_result(
        msg["id"],
        {
            "registered": manager.registered,
            "session": session.state if session else "unavailable",
            "microphone": bool(session and session.microphone_enabled),
            "microphone_busy": bool(manager.microphone_uplink and manager.microphone_uplink.owner),
            "viewers": session.viewer_count if session else 0,
        },
    )


@websocket_api.websocket_command(
    {**BASE, vol.Required("type"): f"{DOMAIN}/start", vol.Required("camera_id"): str}
)
@websocket_api.async_response
async def ws_start(hass, connection, msg) -> None:
    try:
        await _manager(hass, msg["entry_id"]).async_start_monitoring(msg["camera_id"])
    except Exception as error:
        connection.send_error(msg["id"], "start_failed", type(error).__name__)
        return
    connection.send_result(msg["id"])


@websocket_api.websocket_command({**BASE, vol.Required("type"): f"{DOMAIN}/end"})
@websocket_api.async_response
async def ws_end(hass, connection, msg) -> None:
    try:
        await _manager(hass, msg["entry_id"]).async_end_monitoring()
    except Exception as error:
        connection.send_error(msg["id"], "end_failed", type(error).__name__)
        return
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        **BASE,
        vol.Required("type"): f"{DOMAIN}/microphone/negotiate",
        vol.Required("owner"): str,
        vol.Required("offer"): str,
    }
)
@websocket_api.async_response
async def ws_microphone_negotiate(hass, connection, msg) -> None:
    try:
        uplink = _manager(hass, msg["entry_id"]).microphone_uplink
        if uplink is None:
            raise RuntimeError("Microphone unavailable")
        answer = await uplink.negotiate(msg["owner"], msg["offer"])
    except Exception as error:
        connection.send_error(
            msg["id"],
            "microphone_failed",
            f"{type(error).__name__}: {error}",
        )
        return
    connection.send_result(msg["id"], {"answer": answer})


@websocket_api.websocket_command(
    {
        **BASE,
        vol.Required("type"): f"{DOMAIN}/microphone/set",
        vol.Required("owner"): str,
        vol.Required("enabled"): bool,
    }
)
@websocket_api.async_response
async def ws_microphone_set(hass, connection, msg: dict[str, Any]) -> None:
    try:
        uplink = _manager(hass, msg["entry_id"]).microphone_uplink
        if uplink is None:
            raise RuntimeError("Microphone unavailable")
        if msg["enabled"]:
            raise RuntimeError("Negotiate an audio uplink before enabling")
        await uplink.close(msg["owner"])
    except Exception as error:
        connection.send_error(msg["id"], "microphone_failed", type(error).__name__)
        return
    connection.send_result(msg["id"])
