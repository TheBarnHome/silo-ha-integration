"""Diagnostics support for the Silo integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_API_KEY, CONF_URL, CONF_VERIFY_SSL

TO_REDACT = {CONF_API_KEY}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry, with the API key redacted."""
    runtime = entry.runtime_data
    coordinator = runtime.coordinator
    data = coordinator.data
    return {
        "entry": {
            CONF_URL: entry.data.get(CONF_URL),
            CONF_VERIFY_SSL: entry.data.get(CONF_VERIFY_SSL),
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "server": asdict(runtime.server),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval": str(coordinator.update_interval),
            "command_actions": sorted(data.command_actions) if data else [],
            "sensors_enabled": coordinator.sensors_enabled,
        },
        "stats": dict(data.stats) if data and data.stats else None,
        "sessions": [dict(session.raw) for session in data.sessions] if data else [],
    }
