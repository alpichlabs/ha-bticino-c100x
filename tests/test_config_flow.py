"""Configuration-flow helper tests."""

import json

from custom_components.bticino_c100x.config_flow import _lock_choices


def test_lock_choices_include_open_address_and_button() -> None:
    private_address = {
        "addressValues": [{"name": "address", "value": "20"}],
        "buttonId": "1",
    }
    modules = [
        {
            "id": "release-id",
            "device": "lock",
            "name": "",
            "tags": [{"key": "PrivateAddress", "value": json.dumps(private_address)}],
        }
    ]

    assert _lock_choices(modules) == {"release-id": "Door 1 (address 20, button 1)"}
