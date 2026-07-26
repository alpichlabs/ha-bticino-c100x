"""Authentication token lifecycle tests."""

import time
from unittest.mock import AsyncMock

from custom_components.bticino_c100x.auth import C100XAuth


async def test_restored_current_token_does_not_call_network() -> None:
    auth = C100XAuth(AsyncMock(), "person@example.com", "password")
    auth.restore({"access_token": "current", "refresh_token": "refresh", "expires_at": time.time() + 3600})
    assert await auth.access_token() == "current"


async def test_expired_token_refreshes_once() -> None:
    auth = C100XAuth(AsyncMock(), "person@example.com", "password")
    auth.restore({"access_token": "expired", "refresh_token": "refresh", "expires_at": 0})
    auth._refresh = AsyncMock()  # type: ignore[method-assign]

    async def make_valid() -> None:
        auth.restore({"access_token": "renewed", "refresh_token": "next", "expires_at": time.time() + 3600})

    auth._refresh.side_effect = make_valid
    assert await auth.access_token() == "renewed"
    auth._refresh.assert_awaited_once()

