"""Config flow for the Silo integration."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from yarl import URL

from .api import (
    SiloAuthError,
    SiloClient,
    SiloConnectionError,
    SiloError,
    SiloPermissionError,
    SiloUnsupportedApiError,
)
from .const import (
    CONF_API_KEY,
    CONF_ENABLE_SENSORS,
    CONF_EXCLUDE_USERS,
    CONF_INCLUDE_USERS,
    CONF_UPDATE_INTERVAL,
    CONF_URL,
    CONF_VERIFY_SSL,
    DEFAULT_ENABLE_SENSORS,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    UPDATE_INTERVAL_CHOICES,
)

_LOGGER = logging.getLogger(__name__)


def normalize_url(value: str) -> str:
    """Normalize a user-typed server URL, adding a scheme when omitted."""
    candidate = value.strip().rstrip("/")
    if not candidate:
        raise ValueError("empty URL")
    if "://" not in candidate:
        candidate = f"http://{candidate}"
    parsed = URL(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.host:
        raise ValueError("unsupported URL")
    port = f":{parsed.explicit_port}" if parsed.explicit_port else ""
    return f"{parsed.scheme}://{parsed.host}{port}"


class SiloConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for the server URL and an administrator API key."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                url = normalize_url(user_input[CONF_URL])
            except ValueError:
                errors[CONF_URL] = "invalid_url"
            else:
                api_key = user_input[CONF_API_KEY].strip()
                verify_ssl = bool(user_input.get(CONF_VERIFY_SSL, True))
                try:
                    installation_id = await self._async_validate(
                        url, api_key, verify_ssl
                    )
                except SiloAuthError:
                    errors["base"] = "invalid_auth"
                except SiloPermissionError:
                    errors["base"] = "not_admin"
                except SiloUnsupportedApiError:
                    errors["base"] = "unsupported_api"
                except SiloConnectionError:
                    errors["base"] = "cannot_connect"
                except SiloError as err:
                    _LOGGER.debug("Unexpected Silo error during setup: %s", err)
                    errors["base"] = "unknown"
                else:
                    await self.async_set_unique_id(installation_id or url)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=_entry_title(url),
                        data={
                            CONF_URL: url,
                            CONF_API_KEY: api_key,
                            CONF_VERIFY_SSL: verify_ssl,
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL): cv.string,
                    vol.Required(CONF_API_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(CONF_VERIFY_SSL, default=True): cv.boolean,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Start a reauthentication after the API key was refused."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new API key."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        url = entry.data[CONF_URL]
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            try:
                await self._async_validate(
                    url, api_key, bool(entry.data.get(CONF_VERIFY_SSL, True))
                )  # noqa: RUF100 - explicit call, result unused
            except SiloAuthError:
                errors["base"] = "invalid_auth"
            except SiloPermissionError:
                errors["base"] = "not_admin"
            except SiloUnsupportedApiError:
                errors["base"] = "unsupported_api"
            except SiloConnectionError:
                errors["base"] = "cannot_connect"
            except SiloError:
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, CONF_API_KEY: api_key},
                    reason="reauth_successful",
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={CONF_URL: url},
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return SiloOptionsFlow()

    async def _async_validate(
        self, url: str, api_key: str, verify_ssl: bool
    ) -> str | None:
        """Check the server, the API major and the key's authority."""
        session = async_get_clientsession(self.hass, verify_ssl=verify_ssl)
        client = SiloClient(session, url, api_key)
        await client.async_check_api()
        # The administrator session view is the one read this integration
        # cannot work without; a non-admin key is refused here.
        await client.async_session_capabilities()
        try:
            capabilities = await client.async_playback_capabilities()
        except SiloError:
            return None
        value = capabilities.get("installation_id")
        if isinstance(value, str) and value:
            return value
        return None


class SiloOptionsFlow(OptionsFlow):
    """Tune polling, filters and sensors."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the options step."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_UPDATE_INTERVAL,
                        default=options.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                        ),
                    ): vol.In(UPDATE_INTERVAL_CHOICES),
                    vol.Optional(
                        CONF_ENABLE_SENSORS,
                        default=options.get(
                            CONF_ENABLE_SENSORS, DEFAULT_ENABLE_SENSORS
                        ),
                    ): cv.boolean,
                    vol.Optional(
                        CONF_INCLUDE_USERS,
                        default=options.get(CONF_INCLUDE_USERS, ""),
                    ): TextSelector(TextSelectorConfig()),
                    vol.Optional(
                        CONF_EXCLUDE_USERS,
                        default=options.get(CONF_EXCLUDE_USERS, ""),
                    ): TextSelector(TextSelectorConfig()),
                }
            ),
        )


def _entry_title(url: str) -> str:
    """Return a readable title for the config entry."""
    host = urlparse(url).hostname
    return f"Silo ({host})" if host else "Silo"
