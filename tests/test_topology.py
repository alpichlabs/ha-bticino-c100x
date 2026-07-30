"""Official Classe 100X topology-selection tests."""

import json

from custom_components.bticino_c100x.topology import (
    visible_external_units,
    visible_lock_modules,
)


def module(device_type: str, module_id: str, visible: int, button_id: str) -> dict:
    return {
        "id": module_id,
        "deviceType": device_type,
        "tags": [
            {
                "key": "PrivateAddress",
                "value": json.dumps({"visible": visible, "buttonId": button_id}),
            }
        ],
    }


def test_locks_match_official_visibility_query_and_button_order() -> None:
    modules = [
        module("Lock", "hidden-22", 0, "6"),
        module("Lock", "second-visible", 1, "2"),
        module("Lock", "first-visible", 2, "1"),
        module("Lock", "hidden-21", 0, "5"),
    ]

    assert [item["id"] for item in visible_lock_modules(modules)] == [
        "first-visible",
        "second-visible",
    ]


def test_camera_selection_uses_visible_eu_only() -> None:
    modules = [
        module("EU", "hidden-camera", 0, "4"),
        module("IU", "indoor-unit", 0, "0"),
        module("EU", "front-camera", 2, "0"),
    ]

    assert [item["id"] for item in visible_external_units(modules)] == ["front-camera"]
