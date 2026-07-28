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

    assert _lock_choices(modules) == {"release-id": "Door release 1 (address 20, button 1)"}


def test_lock_choices_identify_classe_100x_dedicated_release_key() -> None:
    modules = [
        {
            "id": "main-release-id",
            "device": "lock",
            "name": "Lock",
            "tags": [
                {
                    "key": "PrivateAddress",
                    "value": json.dumps(
                        {
                            "addressValues": [{"name": "address", "value": "22"}],
                            "buttonId": "6",
                        }
                    ),
                }
            ],
        },
        {
            "id": "additional-release-id",
            "device": "lock",
            "name": "Gate",
            "tags": [
                {
                    "key": "PrivateAddress",
                    "value": json.dumps(
                        {
                            "addressValues": [{"name": "address", "value": "21"}],
                            "buttonId": "5",
                        }
                    ),
                }
            ],
        },
    ]

    assert _lock_choices(modules) == {
        "main-release-id": "Main door release (address 22, button 6)",
        "additional-release-id": "Gate (address 21, button 5)",
    }
