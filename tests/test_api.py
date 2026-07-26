"""Legrand API tests."""

from unittest.mock import AsyncMock

import aiohttp
from aioresponses import aioresponses

from custom_components.bticino_c100x.api import LegrandApi
from custom_components.bticino_c100x.const import API_BASE, API_SUBSCRIPTION_KEY


async def test_sip_accounts_use_required_headers() -> None:
    auth = AsyncMock()
    auth.access_token.return_value = "token-value"
    async with aiohttp.ClientSession() as session:
        api = LegrandApi(session, auth)
        url = f"{API_BASE}/vde/sip/v1.0/devices/gateway/sipaccounts"
        with aioresponses() as mocked:
            mocked.get(
                url,
                payload=[
                    {
                        "clientId": "123",
                        "sipUri": "oid_123@gateway.bs.iotleg.com",
                        "sipPassword": "secret",
                        "userOid": "oid",
                    }
                ],
            )
            accounts = await api.sip_accounts("gateway")
            request = next(iter(mocked.requests.values()))[0]
    assert accounts[0].username == "oid_123"
    assert request.kwargs["headers"]["Ocp-Apim-Subscription-Key"] == API_SUBSCRIPTION_KEY
    assert request.kwargs["headers"]["UserToken"] == "token-value"

