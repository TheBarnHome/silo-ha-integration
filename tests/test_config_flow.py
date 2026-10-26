"""Config and options flow tests."""

from __future__ import annotations

from datetime import timedelta

import pytest
from custom_components.silo.const import (
    CONF_API_KEY,
    CONF_ENABLE_SENSORS,
    CONF_EXCLUDE_USERS,
    CONF_INCLUDE_USERS,
    CONF_UPDATE_INTERVAL,
    CONF_URL,
    CONF_VERIFY_SSL,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from . import data
from .const import INSTALLATION_ID, MOCK_API_KEY, MOCK_URL

BASE = f"{MOCK_URL}/api/v2"


def _register_server(aioclient_mock, *, version: int = 2) -> None:
    aioclient_mock.get(
        f"{BASE}/system/info", json=data.system_info_payload(api_major=version)
    )
    aioclient_mock.get(
        f"{BASE}/admin/sessions/capabilities",
        json=data.session_capabilities_payload(),
    )
    aioclient_mock.get(
        f"{BASE}/playback/capabilities", json=data.playback_capabilities_payload()
    )
    # The entry is set up as soon as the flow creates it.
    aioclient_mock.get(
        f"{BASE}/admin/sessions/command-capabilities",
        json=data.command_capabilities_payload(),
    )
    aioclient_mock.get(f"{BASE}/admin/sessions", json=data.sessions_payload([]))
    aioclient_mock.get(f"{BASE}/admin/stats", json=data.stats_payload())


async def test_user_flow_creates_the_entry(hass, aioclient_mock):
    """A reachable server with an admin key creates the entry."""
    _register_server(aioclient_mock)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_URL: MOCK_URL,
            CONF_API_KEY: MOCK_API_KEY,
            CONF_VERIFY_SSL: False,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Silo (silo.test)"
    assert result["data"][CONF_URL] == MOCK_URL
    assert result["data"][CONF_API_KEY] == MOCK_API_KEY
    assert result["result"].unique_id == INSTALLATION_ID


async def test_user_flow_normalizes_the_url(hass, aioclient_mock):
    """A URL without a scheme is completed instead of refused."""
    _register_server(aioclient_mock)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_URL: "silo.test/",
            CONF_API_KEY: MOCK_API_KEY,
            CONF_VERIFY_SSL: False,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_URL] == MOCK_URL


async def test_user_flow_refuses_another_scheme(hass):
    """Only HTTP(S) servers are accepted."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: "ftp://silo.test", CONF_API_KEY: MOCK_API_KEY},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_URL: "invalid_url"}


async def test_user_flow_reports_a_refused_key(hass, aioclient_mock):
    """A 401 on the administrator view is an authentication failure."""
    aioclient_mock.get(f"{BASE}/system/info", json=data.system_info_payload())
    aioclient_mock.get(
        f"{BASE}/admin/sessions/capabilities",
        status=401,
        json={"type": "authentication_required", "detail": "no key"},
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: MOCK_URL, CONF_API_KEY: "bad", CONF_VERIFY_SSL: False},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_reports_a_non_admin_key(hass, aioclient_mock):
    """A regular account cannot read the administrator session view."""
    aioclient_mock.get(f"{BASE}/system/info", json=data.system_info_payload())
    aioclient_mock.get(
        f"{BASE}/admin/sessions/capabilities",
        status=403,
        json={"type": "permission_denied", "detail": "admin only"},
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: MOCK_URL, CONF_API_KEY: MOCK_API_KEY, CONF_VERIFY_SSL: False},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "not_admin"}


async def test_user_flow_reports_an_older_api(hass, aioclient_mock):
    """A server that does not serve API v2 is refused."""
    _register_server(aioclient_mock, version=1)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: MOCK_URL, CONF_API_KEY: MOCK_API_KEY, CONF_VERIFY_SSL: False},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unsupported_api"}


async def test_user_flow_reports_an_unreachable_server(hass, aioclient_mock):
    """A network failure is reported as a connection error."""
    aioclient_mock.get(f"{BASE}/system/info", exc=OSError("boom"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: MOCK_URL, CONF_API_KEY: MOCK_API_KEY, CONF_VERIFY_SSL: False},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reauth_updates_the_key(hass, silo, mock_config_entry):
    """Reauthentication replaces the stored key."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": mock_config_entry.entry_id},
        data=mock_config_entry.data,
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "sa_renewed"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_API_KEY] == "sa_renewed"
    assert mock_config_entry.state is not None


async def test_options_flow_stores_the_settings(hass, silo, mock_config_entry):
    """The options flow persists the polling interval and filters."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_UPDATE_INTERVAL: 30,
            CONF_ENABLE_SENSORS: False,
            CONF_INCLUDE_USERS: "tristan",
            CONF_EXCLUDE_USERS: "",
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_UPDATE_INTERVAL] == 30
    assert mock_config_entry.options[CONF_INCLUDE_USERS] == "tristan"


@pytest.mark.parametrize("value", ["tristan, pauline", "tristan;pauline"])
async def test_user_option_lists_accept_separators(hass, silo, entry_factory, value):
    """Comma and semicolon separated user lists both work."""
    silo.sessions = [data.movie_session(), data.episode_session()]
    mock_config_entry = entry_factory(options={CONF_INCLUDE_USERS: value})

    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert len(hass.states.async_entity_ids("media_player")) == 2


async def test_excluded_user_is_ignored(hass, silo, entry_factory):
    """An excluded account produces no entity."""
    silo.sessions = [data.movie_session(), data.episode_session()]
    mock_config_entry = entry_factory(options={CONF_EXCLUDE_USERS: "pauline"})

    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    states = [
        hass.states.get(entity_id)
        for entity_id in hass.states.async_entity_ids("media_player")
    ]
    assert len(states) == 1
    assert states[0].attributes["username"] == "tristan"


async def test_duplicate_server_is_aborted(hass, aioclient_mock, mock_config_entry):
    """Two entries cannot point at the same installation."""
    _register_server(aioclient_mock)
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: MOCK_URL, CONF_API_KEY: MOCK_API_KEY, CONF_VERIFY_SSL: False},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


__all__ = ["MockConfigEntry"]


async def test_options_accept_a_two_second_interval(hass, silo, mock_config_entry):
    """The polling floor is 2 s for near-instant play/stop reactions."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_UPDATE_INTERVAL: 2,
            CONF_ENABLE_SENSORS: True,
            CONF_INCLUDE_USERS: "",
            CONF_EXCLUDE_USERS: "",
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_UPDATE_INTERVAL] == 2
    assert mock_config_entry.runtime_data.coordinator.update_interval == timedelta(
        seconds=2
    )
