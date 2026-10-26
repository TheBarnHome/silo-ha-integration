"""The Silo integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    SiloAuthError,
    SiloClient,
    SiloConnectionError,
    SiloError,
    SiloPermissionError,
    SiloUnsupportedApiError,
)
from .const import CONF_API_KEY, CONF_URL, CONF_VERIFY_SSL, DOMAIN
from .coordinator import SiloCoordinator, SiloRuntimeData
from .models import SiloServerInfo
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER, Platform.SENSOR]

type SiloConfigEntry = ConfigEntry[SiloRuntimeData]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the integration-wide services."""
    await async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SiloConfigEntry) -> bool:
    """Set up one Silo server from a config entry."""
    session = async_get_clientsession(
        hass, verify_ssl=bool(entry.data.get(CONF_VERIFY_SSL, True))
    )
    client = SiloClient(session, entry.data[CONF_URL], entry.data[CONF_API_KEY])

    try:
        info = await client.async_check_api()
    except SiloUnsupportedApiError as err:
        raise ConfigEntryNotReady(str(err)) from err
    except SiloConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err
    except SiloError as err:
        raise ConfigEntryNotReady(str(err)) from err

    installation_id = await _async_installation_id(client)
    if installation_id is None:
        # Without the persisted installation id the server cannot be
        # distinguished from another one behind the same URL.
        installation_id = entry.unique_id or entry.entry_id

    try:
        capabilities = await client.async_session_capabilities()
    except SiloAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except SiloPermissionError as err:
        raise ConfigEntryAuthFailed(
            "The API key is not owned by an administrator account"
        ) from err
    except SiloError as err:
        raise ConfigEntryNotReady(str(err)) from err

    if capabilities.get("available") is False:
        _LOGGER.warning(
            "Silo at %s reports its playback session view as %s; "
            "the integration keeps polling but will stay idle",
            client.url,
            capabilities.get("state"),
        )

    server = SiloServerInfo(
        installation_id=str(installation_id),
        version=info.get("server_version"),
        url=client.url,
    )
    _LOGGER.debug(
        "Silo %s at %s (installation %s, API %s, contract %s)",
        server.version,
        server.url,
        server.installation_id,
        info.get("api_major"),
        info.get("contract_digest"),
    )

    coordinator = SiloCoordinator(hass, entry, client, server)
    await coordinator.async_load_capabilities()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = SiloRuntimeData(
        client=client, coordinator=coordinator, server=server
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SiloConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: SiloConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_installation_id(client: SiloClient) -> str | None:
    """Read the persisted server installation id, when it is exposed."""
    try:
        capabilities = await client.async_playback_capabilities()
    except SiloError as err:
        _LOGGER.debug("Silo did not expose a playback installation id: %s", err)
        return None
    value = capabilities.get("installation_id")
    if isinstance(value, str) and value:
        return value
    return None
