"""Diagnostics tests."""

from __future__ import annotations

from custom_components.silo.const import CONF_API_KEY
from custom_components.silo.diagnostics import async_get_config_entry_diagnostics
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import data
from .const import INSTALLATION_ID


async def test_diagnostics_redacts_the_key(
    hass: HomeAssistant, silo, mock_config_entry
):
    """Diagnostics expose the sessions but never the credential."""
    silo.sessions = [data.movie_session()]
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    assert diagnostics["entry"]["data"][CONF_API_KEY] == "**REDACTED**"
    assert diagnostics["server"]["installation_id"] == INSTALLATION_ID
    assert diagnostics["sessions"][0]["session_id"] == "10"
    assert diagnostics["coordinator"]["command_actions"] == [
        "message",
        "pause",
        "resume",
        "stop",
        "terminate",
    ]
    assert diagnostics["stats"]["total_movies"] == 800


def test_redaction_helper_covers_the_key():
    """Guard: the key name used for redaction matches the entry data."""
    assert CONF_API_KEY in async_redact_data({CONF_API_KEY: "sa_x"}, {CONF_API_KEY})
