"""Command and service tests."""

from __future__ import annotations

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from . import data


async def _setup(hass, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _entity_id(hass, username: str = "tristan") -> str:
    for entity_id in hass.states.async_entity_ids("media_player"):
        state = hass.states.get(entity_id)
        if state and state.attributes.get("username") == username:
            return entity_id
    raise AssertionError(f"no player for {username}")


@pytest.mark.parametrize(
    ("service", "action"),
    [
        ("media_pause", "pause"),
        ("media_play", "resume"),
        ("media_stop", "stop"),
    ],
)
async def test_transport_services_send_admin_commands(
    hass, silo, mock_config_entry, service, action
):
    """The transport services map onto sequenced administrator commands."""
    silo.sessions = [data.movie_session()]
    await _setup(hass, mock_config_entry)

    await hass.services.async_call(
        "media_player", service, {"entity_id": _entity_id(hass)}, blocking=True
    )

    assert len(silo.command_calls) == 1
    sent_action, payload = silo.command_calls[0]
    assert sent_action == action
    assert payload["reason"] == "Home Assistant"
    assert payload["deadline_ms"] == 3000
    assert len(payload["command_id"]) == 36


async def test_features_follow_the_server_actions(hass, silo, mock_config_entry):
    """Only the actions the server dispatches are advertised."""
    silo.actions = ["pause", "resume"]
    silo.sessions = [data.movie_session()]
    await _setup(hass, mock_config_entry)

    state = hass.states.get(_entity_id(hass))
    assert state is not None
    features = MediaPlayerEntityFeature(state.attributes["supported_features"])
    assert features == MediaPlayerEntityFeature.PAUSE | MediaPlayerEntityFeature.PLAY


async def test_no_command_without_a_session(hass, silo, mock_config_entry):
    """A player restored as idle has nothing to control."""
    silo.sessions = [data.movie_session()]
    await _setup(hass, mock_config_entry)
    entity_id = _entity_id(hass)

    silo.sessions = []
    await mock_config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "media_player", "media_pause", {"entity_id": entity_id}, blocking=True
        )
    assert silo.command_calls == []


async def test_refused_command_raises(hass, silo, mock_config_entry):
    """A server refusal becomes a Home Assistant error, not a silent no-op."""
    silo.sessions = [data.movie_session()]
    await _setup(hass, mock_config_entry)
    silo.command_status = 409

    with pytest.raises(HomeAssistantError, match="Silo refused"):
        await hass.services.async_call(
            "media_player",
            "media_pause",
            {"entity_id": _entity_id(hass)},
            blocking=True,
        )


async def test_send_message_service(hass, silo, mock_config_entry):
    """The message service displays text on the player."""
    silo.sessions = [data.movie_session()]
    await _setup(hass, mock_config_entry)

    await hass.services.async_call(
        "silo",
        "send_message",
        {
            "entity_id": _entity_id(hass),
            "message": "Le film reprend dans 5 minutes.",
            "title": "Maison",
        },
        blocking=True,
    )

    action, payload = silo.command_calls[0]
    assert action == "message"
    assert payload["message"] == "Le film reprend dans 5 minutes."
    assert payload["title"] == "Maison"


async def test_terminate_service(hass, silo, mock_config_entry):
    """Terminating revokes the session authority, distinct from stop."""
    silo.sessions = [data.movie_session()]
    await _setup(hass, mock_config_entry)

    await hass.services.async_call(
        "silo",
        "terminate_session",
        {"entity_id": _entity_id(hass), "reason": "Test"},
        blocking=True,
    )

    action, payload = silo.command_calls[0]
    assert action == "terminate"
    assert payload["reason"] == "Test"


async def test_scan_library_service(hass, silo, mock_config_entry):
    """The scan service forwards to the library scan endpoint."""
    silo.sessions = []
    await _setup(hass, mock_config_entry)

    await hass.services.async_call(
        "silo",
        "scan_library",
        {"library_id": "3", "path": "/media/films"},
        blocking=True,
    )

    assert silo.scan_calls == [{"library_id": "3", "path": "/media/films"}]


async def test_scan_library_refusal_is_reported(hass, silo, mock_config_entry):
    """A refused scan surfaces as a validation error."""
    silo.sessions = []
    await _setup(hass, mock_config_entry)
    silo.scan_status = 404

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "silo", "scan_library", {"library_id": "404"}, blocking=True
        )
