"""Legrand cloud API client."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .auth import C100XAuth
from .const import API_BASE, API_SUBSCRIPTION_KEY
from .models import SipAccount

_LOGGER = logging.getLogger(__name__)


class ApiError(Exception):
    """A sanitized Legrand API error."""

    def __init__(self, status: int, operation: str) -> None:
        super().__init__(f"Legrand API {operation} failed with HTTP {status}")
        self.status = status


class LegrandApi:
    """Small API surface required by the integration."""

    def __init__(self, session: aiohttp.ClientSession, auth: C100XAuth) -> None:
        self._session = session
        self._auth = auth

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        diagnostic_label: str | None = None,
    ) -> Any:
        for attempt in range(3):
            token = await self._auth.access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "UserToken": token,
                "Ocp-Apim-Subscription-Key": API_SUBSCRIPTION_KEY,
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
            async with self._session.request(method, f"{API_BASE}{path}", headers=headers, json=payload) as response:
                if response.status >= 500 and attempt < 2:
                    await asyncio.sleep(2**attempt)
                    continue
                if response.status >= 400:
                    raise ApiError(response.status, f"{method} {path}")
                if response.status == 204:
                    if diagnostic_label:
                        _LOGGER.debug("%s accepted: HTTP 204, empty response", diagnostic_label)
                    return None
                value = await response.json(content_type=None)
                if diagnostic_label:
                    _LOGGER.debug(
                        "%s accepted: HTTP %s, response %s",
                        diagnostic_label,
                        response.status,
                        _response_summary(value),
                    )
                return value
        raise ApiError(503, f"{method} {path}")

    async def plants(self) -> list[dict]:
        value = await self._request("GET", "/servicecatalog/api/v3.0/plants")
        return value if isinstance(value, list) else value.get("plants", value.get("value", []))

    async def plant(self, plant_id: str) -> dict:
        value = await self._request("GET", f"/servicecatalog/api/v3.0/plants/{plant_id}")
        return value.get("plant", value)

    async def modules(self, plant_id: str) -> list[dict]:
        value = await self._request("GET", f"/servicecatalog/api/v3.0/plants/{plant_id}/modules")
        return value if isinstance(value, list) else value.get("modules", value.get("value", []))

    async def release_door(self, gateway_id: str, lock_id: str) -> None:
        """Pulse a connected electric strike through the Door Entry cloud."""
        await self._request(
            "POST",
            f"/devicemanagement/api/v2.0/modules/{gateway_id}/commands",
            {"command": {"name": "open", "moduleId": lock_id}},
            diagnostic_label="Door release command",
        )

    async def sip_accounts(self, gateway_id: str) -> list[SipAccount]:
        value = await self._request("GET", f"/vde/sip/v1.0/devices/{gateway_id}/sipaccounts")
        return [SipAccount.from_api(item) for item in value]

    async def register_sip_account(self, gateway_id: str, client_id: str) -> SipAccount:
        user_oid = await self._auth.user_oid()
        sip_uri = f"{user_oid}_{client_id}@{gateway_id}.bs.iotleg.com"
        value = await self._request(
            "POST",
            f"/vde/sip/v1.0/devices/{gateway_id}/sipaccount",
            {"clientId": client_id, "clientName": "Home Assistant", "sipUri": sip_uri},
        )
        return SipAccount.from_api(value)

    async def provision_certificate(self, request: dict) -> dict:
        return await self._request("POST", "/certificate/api/v1.0/ca/information/clientCerts", request)


def _response_summary(value: Any) -> str:
    """Describe a response without logging values or installation identifiers."""
    if isinstance(value, dict):
        keys = ", ".join(sorted(str(key) for key in value))
        return f"object with keys [{keys}]" if keys else "empty object"
    if isinstance(value, list):
        return f"list with {len(value)} item(s)"
    if value is None:
        return "null"
    return type(value).__name__
