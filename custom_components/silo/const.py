"""Constants for the Silo integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "silo"

# The native, stable API surface. Everything this integration calls lives below
# this prefix; the alpha /api/v1 bridge is deliberately unused (it is retired at
# Silo 1.0 with a 410).
API_PREFIX: Final = "/api/v2"

MANUFACTURER: Final = "Silo"

DEFAULT_TIMEOUT: Final = 10
DEFAULT_UPDATE_INTERVAL: Final = 10
UPDATE_INTERVAL_CHOICES: Final = (5, 10, 15, 30, 60, 120, 300)

# Statistics are far less volatile than live sessions.
STATS_REFRESH_SECONDS: Final = 300

# Delivery acknowledgement deadline the server applies to sequenced commands.
COMMAND_DEADLINE_MS: Final = 3000
COMMAND_REASON: Final = "Home Assistant"

# A stale sequence refuses the command and reports the applied sequence in this
# header, so the integration can allocate a newer one instead of guessing.
LATEST_SEQUENCE_HEADER: Final = "X-Silo-Latest-Sequence"

CONF_URL: Final = "url"
CONF_API_KEY: Final = "api_key"
CONF_VERIFY_SSL: Final = "verify_ssl"
CONF_UPDATE_INTERVAL: Final = "update_interval"
CONF_INCLUDE_USERS: Final = "include_users"
CONF_EXCLUDE_USERS: Final = "exclude_users"
CONF_ENABLE_SENSORS: Final = "enable_sensors"
CONF_PROFILE_ID: Final = "profile_id"

DEFAULT_ENABLE_SENSORS: Final = True

# Command actions the administrator API can dispatch.
ACTION_PAUSE: Final = "pause"
ACTION_RESUME: Final = "resume"
ACTION_STOP: Final = "stop"
ACTION_MESSAGE: Final = "message"
ACTION_TERMINATE: Final = "terminate"
