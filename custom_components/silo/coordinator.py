"""Coordinator polling the Silo server."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    SiloAuthError,
    SiloClient,
    SiloConflictError,
    SiloError,
    SiloPermissionError,
    SiloRateLimitError,
)
from .const import (
    ACTION_MESSAGE,
    ACTION_PAUSE,
    ACTION_RESUME,
    ACTION_STOP,
    ACTION_TERMINATE,
    CONF_ENABLE_SENSORS,
    CONF_EXCLUDE_USERS,
    CONF_INCLUDE_USERS,
    CONF_UPDATE_INTERVAL,
    DEFAULT_ENABLE_SENSORS,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    STATS_REFRESH_SECONDS,
)
from .models import SiloServerInfo, SiloSession, SiloSnapshot

_LOGGER = logging.getLogger(__name__)

# Capability documents change far less often than the session list.
CAPABILITIES_REFRESH_SECONDS = 600

KNOWN_ACTIONS = frozenset(
    {ACTION_PAUSE, ACTION_RESUME, ACTION_STOP, ACTION_MESSAGE, ACTION_TERMINATE}
)


@dataclass(slots=True)
class SiloRuntimeData:
    """Objects shared by the platforms of one config entry."""

    client: SiloClient
    coordinator: SiloCoordinator
    server: SiloServerInfo


class SiloCoordinator(DataUpdateCoordinator[SiloSnapshot]):
    """Poll the live administrator session view."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: SiloClient,
        server: SiloServerInfo,
    ) -> None:
        """Initialize the coordinator with the entry interval and filters."""
        interval = entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {server.url}",
            update_interval=timedelta(seconds=int(interval)),
        )
        self.client = client
        self.server = server
        self.sensors_enabled = entry.options.get(
            CONF_ENABLE_SENSORS, DEFAULT_ENABLE_SENSORS
        )
        self._include_users = _user_set(entry.options.get(CONF_INCLUDE_USERS))
        self._exclude_users = _user_set(entry.options.get(CONF_EXCLUDE_USERS))
        self._command_actions: frozenset[str] = frozenset()
        self._capabilities_at = 0.0
        self._stats: Mapping[str, Any] | None = None
        self._stats_at = 0.0

    async def async_load_capabilities(self) -> None:
        """Read the administrator command capabilities once at setup."""
        await self._async_refresh_command_actions(force=True)

    async def _async_refresh_command_actions(self, *, force: bool = False) -> None:
        """Refresh the dispatched action set, never failing the poll."""
        if (
            not force
            and self._command_actions
            and time.monotonic() - self._capabilities_at < CAPABILITIES_REFRESH_SECONDS
        ):
            return
        try:
            capabilities = await self.client.async_command_capabilities()
        except SiloAuthError:
            raise
        except (SiloPermissionError, SiloError) as err:
            _LOGGER.debug("Silo command capabilities unavailable: %s", err)
            self._command_actions = frozenset()
            self._capabilities_at = time.monotonic()
            return
        actions = capabilities.get("actions")
        if isinstance(actions, list):
            self._command_actions = frozenset(
                action for action in actions if action in KNOWN_ACTIONS
            )
        else:
            self._command_actions = frozenset()
        self._capabilities_at = time.monotonic()

    async def _async_stats(self) -> Mapping[str, Any] | None:
        """Return the dashboard statistics, refreshed at their own pace."""
        if not self.sensors_enabled:
            return None
        if (
            self._stats is not None
            and time.monotonic() - self._stats_at < STATS_REFRESH_SECONDS
        ):
            return self._stats
        try:
            self._stats = await self.client.async_stats()
        except SiloAuthError:
            raise
        except (SiloPermissionError, SiloError) as err:
            _LOGGER.debug("Silo statistics unavailable: %s", err)
            self._stats_at = time.monotonic()
            return self._stats
        self._stats_at = time.monotonic()
        return self._stats

    def _keep_user(self, username: str | None) -> bool:
        """Apply the configured include/exclude user filters."""
        if not username:
            return not self._include_users
        name = username.casefold()
        if name in self._exclude_users:
            return False
        if self._include_users:
            return name in self._include_users
        return True

    async def _async_update_data(self) -> SiloSnapshot:
        """Read every live session and rebuild the snapshot."""
        try:
            payloads = await self.client.async_sessions()
            await self._async_refresh_command_actions()
            stats = await self._async_stats()
        except SiloAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SiloRateLimitError as err:
            raise UpdateFailed(f"Rate limited by Silo: {err}") from err
        except SiloConflictError as err:
            raise UpdateFailed(f"Silo refused the read: {err}") from err
        except SiloError as err:
            raise UpdateFailed(f"Cannot read Silo: {err}") from err

        sessions: list[SiloSession] = []
        for payload in payloads:
            session = SiloSession.from_payload(payload)
            if session is None or not self._keep_user(session.username):
                continue
            sessions.append(session)

        return SiloSnapshot.build(sessions, self._command_actions, stats=stats)

    async def async_send_command(
        self,
        session_id: str,
        action: str,
        *,
        message: str | None = None,
        title: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Dispatch a command and surface Silo's refusal as a friendly error.

        Errors are returned, not raised: the caller owns the Home Assistant
        exception type (entity command or service call).
        """
        return await self.client.async_command(
            session_id, action, message=message, title=title, reason=reason
        )


def _user_set(value: Any) -> set[str]:
    """Normalize an option holding user names into a lowercase set."""
    if not value:
        return set()
    if isinstance(value, str):
        parts = value.replace(";", ",").split(",")
    elif isinstance(value, list):
        parts = value
    else:
        return set()
    return {str(part).strip().casefold() for part in parts if str(part).strip()}
