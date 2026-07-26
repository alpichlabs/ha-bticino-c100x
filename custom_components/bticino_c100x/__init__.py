"""BTicino C100X Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.storage import Store

from .api import ApiError, LegrandApi
from .auth import AuthenticationError, C100XAuth
from .const import DOMAIN, PLATFORMS, STORAGE_VERSION
from .manager import C100XManager
from .sip import SipError


@dataclass(slots=True)
class RuntimeData:
    manager: C100XManager


type C100XConfigEntry = ConfigEntry[RuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: C100XConfigEntry) -> bool:
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    session = async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar())
    token_store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.tokens.{entry.entry_id}")

    async def save_tokens(tokens: dict) -> None:
        await token_store.async_save(tokens)

    auth = C100XAuth(session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD], save_tokens)
    if tokens := await token_store.async_load():
        auth.restore(tokens)
    api = LegrandApi(session, auth)
    manager = C100XManager(hass, entry, auth, api)
    try:
        await manager.async_start()
    except AuthenticationError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except ApiError as err:
        if err.status in (401, 403):
            raise ConfigEntryAuthFailed(str(err)) from err
        raise ConfigEntryNotReady(str(err)) from err
    except (OSError, SipError) as err:
        raise ConfigEntryNotReady(str(err)) from err

    entry.runtime_data = RuntimeData(manager)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: C100XConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: C100XConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.manager.async_stop()
    return True


async def async_remove_entry(hass: HomeAssistant, entry: C100XConfigEntry) -> None:
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.tokens.{entry.entry_id}").async_remove()
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()
