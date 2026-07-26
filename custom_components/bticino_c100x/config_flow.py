"""Configuration flow for BTicino C100X."""

from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import ApiError, LegrandApi
from .auth import AuthenticationError, C100XAuth
from .const import CONF_GATEWAY_ID, CONF_HOME_ID, CONF_LOCK_IDS, DOMAIN


class C100XConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._credentials: dict[str, str] = {}
        self._plants: list[dict] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        schema = vol.Schema({vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str})
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=schema)
        session = async_create_clientsession(
            self.hass, auto_cleanup=False, cookie_jar=aiohttp.CookieJar()
        )
        auth = C100XAuth(session, user_input[CONF_USERNAME], user_input[CONF_PASSWORD])
        try:
            await auth.authenticate()
            self._plants = await LegrandApi(session, auth).plants()
        except AuthenticationError:
            return self.async_show_form(step_id="user", data_schema=schema, errors={"base": "invalid_auth"})
        except (ApiError, OSError):
            return self.async_show_form(step_id="user", data_schema=schema, errors={"base": "cannot_connect"})
        finally:
            session.detach()
        if not self._plants:
            return self.async_abort(reason="no_homes")
        await self.async_set_unique_id(user_input[CONF_USERNAME].strip().casefold())
        self._abort_if_unique_id_configured()
        self._credentials = dict(user_input)
        if len(self._plants) == 1:
            return await self._finish(self._plants[0]["id"])
        return await self.async_step_home()

    async def async_step_home(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        homes = {plant["id"]: plant.get("name", plant["id"]) for plant in self._plants}
        schema = vol.Schema({vol.Required(CONF_HOME_ID): vol.In(homes)})
        if user_input is None:
            return self.async_show_form(step_id="home", data_schema=schema)
        return await self._finish(user_input[CONF_HOME_ID])

    async def _finish(self, home_id: str) -> config_entries.ConfigFlowResult:
        session = async_create_clientsession(
            self.hass, auto_cleanup=False, cookie_jar=aiohttp.CookieJar()
        )
        auth = C100XAuth(session, self._credentials[CONF_USERNAME], self._credentials[CONF_PASSWORD])
        api = LegrandApi(session, auth)
        try:
            modules = await api.modules(home_id)
        except (AuthenticationError, ApiError, OSError):
            return self.async_abort(reason="cannot_connect")
        finally:
            session.detach()
        gateway = next((module for module in modules if module.get("device") == "gateway"), None)
        lock_ids = [module["id"] for module in modules if module.get("device") == "lock"]
        if not gateway or not lock_ids:
            return self.async_abort(reason="unsupported_installation")
        plant = next(plant for plant in self._plants if plant["id"] == home_id)
        return self.async_create_entry(
            title=plant.get("name", "BTicino C100X"),
            data={
                **self._credentials,
                CONF_HOME_ID: home_id,
                CONF_GATEWAY_ID: gateway["id"],
                CONF_LOCK_IDS: lock_ids,
            },
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> config_entries.ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="cannot_connect")
        schema = vol.Schema({vol.Required(CONF_PASSWORD): str})
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm", data_schema=schema)
        session = async_create_clientsession(
            self.hass, auto_cleanup=False, cookie_jar=aiohttp.CookieJar()
        )
        auth = C100XAuth(session, entry.data[CONF_USERNAME], user_input[CONF_PASSWORD])
        try:
            await auth.authenticate()
        except AuthenticationError:
            return self.async_show_form(
                step_id="reauth_confirm", data_schema=schema, errors={"base": "invalid_auth"}
            )
        except OSError:
            return self.async_show_form(
                step_id="reauth_confirm", data_schema=schema, errors={"base": "cannot_connect"}
            )
        finally:
            session.detach()
        self.hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
        )
        await self.hass.config_entries.async_reload(entry.entry_id)
        return self.async_abort(reason="reauth_successful")
