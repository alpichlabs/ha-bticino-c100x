"""Classe 100X topology rules recovered from the official application."""

from __future__ import annotations

import json
from typing import Any

VISIBLE_BUTTON_VALUES = {1, 2}


def private_address(module: dict[str, Any]) -> dict[str, Any] | None:
    """Return the decoded PrivateAddress tag used by the official app."""
    for tag in module.get("tags") or []:
        if tag.get("key") != "PrivateAddress":
            continue
        value = tag.get("value")
        if isinstance(value, dict):
            return value
        if not isinstance(value, str):
            return None
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return None
        return decoded if isinstance(decoded, dict) else None
    return None


def topology_device_type(module: dict[str, Any]) -> str:
    """Normalize the two device-type fields returned by catalog variants."""
    return str(module.get("deviceType") or module.get("device") or "").casefold()


def visible_button(module: dict[str, Any]) -> bool:
    """Apply the official app's visibility IN (1, 2) database query."""
    address = private_address(module)
    if address is None:
        return False
    try:
        return int(address.get("visible", 0)) in VISIBLE_BUTTON_VALUES
    except (TypeError, ValueError):
        return False


def button_id(module: dict[str, Any]) -> int:
    """Return the official-app ordering key, defaulting like its local model."""
    address = private_address(module)
    try:
        return int((address or {}).get("buttonId", 0))
    except (TypeError, ValueError):
        return 0


def visible_lock_modules(modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return every official-app-visible Lock, ordered by buttonId."""
    locks = [
        module
        for module in modules
        if topology_device_type(module) == "lock" and visible_button(module)
    ]
    return sorted(locks, key=button_id)


def visible_staircase_modules(
    modules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return every official-app-visible Staircase actuator, ordered by buttonId."""
    staircases = [
        module
        for module in modules
        if topology_device_type(module) == "staircase" and visible_button(module)
    ]
    return sorted(staircases, key=button_id)

def visible_external_units(modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return official-app-visible external units, ordered by buttonId."""
    units = [
        module
        for module in modules
        if topology_device_type(module) == "eu" and visible_button(module)
    ]
    return sorted(units, key=button_id)


def open_address(module: dict[str, Any]) -> str | None:
    """Extract the 2-wire OPEN address for diagnostics and correlation."""
    address = private_address(module)
    for item in (address or {}).get("addressValues") or []:
        if item.get("name") == "address" and item.get("value") is not None:
            return str(item["value"])
    return None
