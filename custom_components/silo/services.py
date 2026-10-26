"""Services exposed by the Silo integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import (
    SiloAuthError,
    SiloConflictError,
    SiloError,
    SiloNotFoundError,
    SiloPermissionError,
    SiloRateLimitError,
)
from .const import ACTION_TERMINATE, COMMAND_REASON, CONF_URL, DOMAIN
from .coordinator import SiloCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_SEND_MESSAGE = "send_message"
SERVICE_TERMINATE_SESSION = "terminate_session"
SERVICE_SCAN_LIBRARY = "scan_library"

ATTR_MESSAGE = "message"
ATTR_TITLE = "title"
ATTR_REASON = "reason"
ATTR_LIBRARY_ID = "library_id"
ATTR_PATH = "path"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"

# Entity services take a plain dict: Home Assistant wraps it in its own entity
# service schema and refuses a pre-built vol.Schema.
SEND_MESSAGE_SCHEMA = {
    vol.Required(ATTR_MESSAGE): cv.string,
    vol.Optional(ATTR_TITLE): cv.string,
    vol.Optional(ATTR_REASON): cv.string,
}

TERMINATE_SESSION_SCHEMA = {vol.Optional(ATTR_REASON): cv.string}

SCAN_LIBRARY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_LIBRARY_ID): cv.string,
        vol.Optional(ATTR_PATH): cv.string,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)


async def async_dispatch_command(
    coordinator: SiloCoordinator,
    session_id: str,
    action: str,
    *,
    message: str | None = None,
    title: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Send an administrator command and translate refusals into HA errors."""
    try:
        receipt = await coordinator.async_send_command(
            session_id,
            action,
            message=message,
            title=title,
            reason=reason or COMMAND_REASON,
        )
    except SiloNotFoundError as err:
        await coordinator.async_request_refresh()
        raise HomeAssistantError("Silo: this playback session has ended") from err
    except SiloConflictError as err:
        raise HomeAssistantError(f"Silo refused the command: {err}") from err
    except SiloPermissionError as err:
        raise HomeAssistantError(
            "Silo: the API key is not owned by an administrator account"
        ) from err
    except SiloAuthError as err:
        raise HomeAssistantError("Silo: the API key was refused") from err
    except SiloRateLimitError as err:
        raise HomeAssistantError(
            f"Silo rate limited the command (retry in {err.retry_after}s)"
        ) from err
    except SiloError as err:
        raise HomeAssistantError(f"Silo command failed: {err}") from err

    _LOGGER.debug(
        "Silo %s on session %s: outcome=%s delivery=%s sequence=%s",
        action,
        session_id,
        receipt.get("outcome"),
        receipt.get("delivery"),
        receipt.get("sequence"),
    )
    await coordinator.async_request_refresh()
    return receipt


async def async_terminate_session(
    coordinator: SiloCoordinator,
    session_id: str,
    reason: str | None = None,
) -> None:
    """Revoke a session's playback authority, distinct from a graceful stop."""
    await async_dispatch_command(
        coordinator, session_id, ACTION_TERMINATE, reason=reason
    )


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration-wide services once."""
    if hass.services.has_service(DOMAIN, SERVICE_SCAN_LIBRARY):
        return

    async def _async_scan_library(call: ServiceCall) -> None:
        runtime = _runtime_for_call(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        try:
            await runtime.client.async_scan(
                str(call.data[ATTR_LIBRARY_ID]), call.data.get(ATTR_PATH)
            )
        except SiloError as err:
            raise ServiceValidationError(
                f"Silo refused the library scan: {err}"
            ) from err
        _LOGGER.info(
            "Silo scan requested for library %s on %s",
            call.data[ATTR_LIBRARY_ID],
            runtime.server.url,
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SCAN_LIBRARY,
        _async_scan_library,
        schema=SCAN_LIBRARY_SCHEMA,
    )


def _runtime_for_call(hass: HomeAssistant, entry_id: str | None):
    """Resolve the config entry a service call targets."""
    if entry_id:
        entry: ConfigEntry | None = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(f"Unknown config entry {entry_id}")
    else:
        entries = [
            candidate
            for candidate in hass.config_entries.async_entries(DOMAIN)
            if getattr(candidate, "runtime_data", None) is not None
        ]
        if len(entries) != 1:
            raise ServiceValidationError(
                "Several Silo servers are configured; pass config_entry_id"
            )
        entry = entries[0]

    if getattr(entry, "runtime_data", None) is None:
        raise ServiceValidationError("This Silo config entry is not loaded")
    return entry.runtime_data


def entry_url(entry: ConfigEntry) -> str:
    """Return a config entry's server URL, for diagnostics."""
    return str(entry.data.get(CONF_URL, ""))
