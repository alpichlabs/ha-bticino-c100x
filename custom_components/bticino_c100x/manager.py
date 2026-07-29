"""Runtime orchestration for one BTicino installation."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .api import LegrandApi
from .auth import C100XAuth
from .certificate import certificate_expiry, provision_certificate
from .const import (
    CERTIFICATE_RENEWAL_DAYS,
    CONF_GATEWAY_ID,
    CONF_HOME_ID,
    DOMAIN,
    EVENT_RING,
    RING_ACTIVE_SECONDS,
    SIP_RECONNECT_SECONDS,
    SIP_REREGISTER_SECONDS,
    STORAGE_VERSION,
)
from .models import SipAccount
from .sip import SipClient, SipError

_LOGGER = logging.getLogger(__name__)


class C100XManager:
    """Own credentials, mTLS material, and the persistent SIP connection."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        auth: C100XAuth,
        api: LegrandApi,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.auth = auth
        self.api = api
        self.registered = False
        self.ringing = False
        self.last_ring: datetime | None = None
        self.certificate_expires_at: datetime | None = None
        self.last_error: str | None = None
        self._listeners: set[Callable[[], None]] = set()
        self._ring_listeners: set[Callable[[dict[str, Any]], None]] = set()
        self._seen_call_ids: set[str] = set()
        self._supervisor: asyncio.Task | None = None
        self._ring_reset: asyncio.TimerHandle | None = None
        self._client: SipClient | None = None
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._material_dir = Path(hass.config.path(".storage", DOMAIN, entry.entry_id))
        self._certificate_path = self._material_dir / "client.crt"
        self._private_key_path = self._material_dir / "client.key"

    async def async_start(self) -> None:
        account = await self._prepare_account_and_certificate()
        await self._connect(account)
        self._supervisor = asyncio.create_task(self._supervise(account), name=f"{DOMAIN}-{self.entry.entry_id}")

    async def async_stop(self) -> None:
        if self._ring_reset:
            self._ring_reset.cancel()
            self._ring_reset = None
        if self._supervisor:
            self._supervisor.cancel()
            await asyncio.gather(self._supervisor, return_exceptions=True)
            self._supervisor = None
        if self._client:
            await self._client.close()
            self._client = None
        self.registered = False

    async def async_release(self, lock_id: str) -> None:
        if not self._client or not self._client.registered:
            raise SipError("Door release is unavailable while SIP is disconnected")
        await self._client.release_door(
            lock_id,
            self.entry.data[CONF_GATEWAY_ID],
        )

    @callback
    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)

        def remove() -> None:
            self._listeners.discard(listener)

        return remove

    @callback
    def add_ring_listener(self, listener: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        self._ring_listeners.add(listener)

        def remove() -> None:
            self._ring_listeners.discard(listener)

        return remove

    async def _prepare_account_and_certificate(self) -> SipAccount:
        stored = await self._store.async_load() or {}
        client_id = str(stored.get("client_id") or self._new_client_id())
        gateway_id = self.entry.data[CONF_GATEWAY_ID]
        accounts = await self.api.sip_accounts(gateway_id)
        account = next((candidate for candidate in accounts if candidate.client_id == client_id), None)
        if account is None:
            account = await self.api.register_sip_account(gateway_id, client_id)

        needs_certificate = not await self.hass.async_add_executor_job(self._certificate_is_current)
        if needs_certificate:
            plant = await self.api.plant(self.entry.data[CONF_HOME_ID])
            bundle = await provision_certificate(
                self.api,
                plant=plant,
                gateway_id=gateway_id,
                client_id=client_id,
                user_oid=account.user_oid or await self.auth.user_oid(),
            )
            await self.hass.async_add_executor_job(
                self._write_material,
                bundle.certificate_pem,
                bundle.private_key_pem,
            )
            self.certificate_expires_at = bundle.expires_at
        await self._store.async_save({"client_id": client_id})
        return account

    def _certificate_is_current(self) -> bool:
        if not self._certificate_path.is_file() or not self._private_key_path.is_file():
            return False
        try:
            self.certificate_expires_at = certificate_expiry(self._certificate_path.read_text())
        except (OSError, ValueError):
            return False
        return self.certificate_expires_at > datetime.now(UTC) + timedelta(days=CERTIFICATE_RENEWAL_DAYS)

    def _write_material(self, certificate_pem: str, private_key_pem: str) -> None:
        self._material_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._material_dir.chmod(0o700)
        self._certificate_path.write_text(certificate_pem)
        self._private_key_path.write_text(private_key_pem)
        self._certificate_path.chmod(0o600)
        self._private_key_path.chmod(0o600)

    async def _connect(self, account: SipAccount) -> None:
        client = SipClient(
            account,
            str(self._certificate_path),
            str(self._private_key_path),
            self._async_ring,
        )
        await client.connect()
        self._client = client
        self.registered = True
        self.last_error = None
        self._notify()

    async def _supervise(self, account: SipAccount) -> None:
        while True:
            try:
                assert self._client is not None
                await asyncio.wait_for(self._client.wait_closed(), timeout=SIP_REREGISTER_SECONDS)
                raise SipError("SIP connection ended")
            except TimeoutError:
                try:
                    await self._client.register()
                    continue
                except Exception as err:
                    self.last_error = type(err).__name__
            except asyncio.CancelledError:
                raise
            except Exception as err:
                self.last_error = type(err).__name__
            self.registered = False
            self._notify()
            if self._client:
                with contextlib.suppress(Exception):
                    await self._client.close()
                self._client = None
            await asyncio.sleep(SIP_RECONNECT_SECONDS)
            try:
                await self._connect(account)
            except asyncio.CancelledError:
                raise
            except Exception as err:
                self.last_error = type(err).__name__
                _LOGGER.warning("BTicino SIP reconnect failed: %s", type(err).__name__)

    async def _async_ring(self, event: dict[str, Any]) -> None:
        call_id = str(event.get("call_id", ""))
        if call_id and call_id in self._seen_call_ids:
            return
        if call_id:
            self._seen_call_ids.add(call_id)
            if len(self._seen_call_ids) > 100:
                self._seen_call_ids.pop()
        self.last_ring = datetime.now(UTC)
        self.ringing = True
        safe_event = {"call_id": call_id}
        self.hass.bus.async_fire(
            EVENT_RING,
            {CONF_GATEWAY_ID: self.entry.data[CONF_GATEWAY_ID], **safe_event},
        )
        for listener in tuple(self._ring_listeners):
            listener(safe_event)
        self._notify()
        if self._ring_reset:
            self._ring_reset.cancel()
        self._ring_reset = self.hass.loop.call_later(RING_ACTIVE_SECONDS, self._clear_ring)

    @callback
    def _clear_ring(self) -> None:
        self._ring_reset = None
        self.ringing = False
        self._notify()

    @callback
    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    @staticmethod
    def _new_client_id() -> str:
        return str(secrets.randbelow(9) + 1) + "".join(str(secrets.randbelow(10)) for _ in range(21))
