"""Setup, entity creation and polling tests."""

from __future__ import annotations

from datetime import timedelta

from custom_components.silo.const import CONF_UPDATE_INTERVAL, DOMAIN
from custom_components.silo.models import SiloSession
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from . import data
from .const import INSTALLATION_ID


async def _setup(hass, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _players(hass) -> list:
    return [
        hass.states.get(entity_id)
        for entity_id in hass.states.async_entity_ids("media_player")
    ]


def _player_for(hass, username: str):
    for state in _players(hass):
        if state and state.attributes.get("username") == username:
            return state
    raise AssertionError(f"no player for {username}")


async def test_setup_creates_one_player_per_client(hass, silo, mock_config_entry):
    """Two live clients produce two media players."""
    silo.sessions = [data.movie_session(), data.episode_session()]

    await _setup(hass, mock_config_entry)

    assert len(_players(hass)) == 2

    tristan = _player_for(hass, "tristan")
    assert tristan.state == "playing"
    assert tristan.attributes["media_content_id"] == "9001"
    assert tristan.attributes["media_content_type"] == "movie"
    assert tristan.attributes["media_title"] == "Dune: Deuxième partie"
    assert tristan.attributes["media_duration"] == 9300
    assert tristan.attributes["media_position"] == 2110.5
    assert tristan.attributes["media_position_updated_at"] is not None
    assert tristan.attributes["session_id"] == "10"
    assert tristan.attributes["client_label"] == "Silo Web 1.4.2"
    assert tristan.attributes["play_method"] == "direct"
    assert tristan.attributes["stream_location"] == "local"
    assert tristan.attributes["node_display_name"] == "silo-worker-0"
    assert tristan.attributes["platform"] == "macOS"
    assert "media_series_title" not in tristan.attributes

    pauline = _player_for(hass, "pauline")
    assert pauline.state == "paused"
    assert pauline.attributes["media_title"] == "Qui est vivant ?"
    assert pauline.attributes["media_series_title"] == "Severance"
    assert pauline.attributes["media_season"] == 2
    assert pauline.attributes["media_episode"] == 3
    assert pauline.attributes["effective_play_method"] == "transcode"
    assert pauline.attributes["transcode_hw_accel"] == "qsv"
    assert pauline.attributes["target_resolution"] == "1080p"
    assert pauline.attributes["stream_location"] == "remote"


async def test_player_falls_back_to_idle(hass, silo, mock_config_entry):
    """A client that stops playing becomes idle, never unavailable."""
    silo.sessions = [data.movie_session()]
    await _setup(hass, mock_config_entry)
    entity_id = _player_for(hass, "tristan").entity_id
    assert hass.states.get(entity_id).state == "playing"

    silo.sessions = []
    await mock_config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "idle"
    assert state.attributes.get("session_id") is None


async def test_polling_picks_up_a_new_session(hass, silo, mock_config_entry):
    """The coordinator interval is what discovers playback."""
    silo.sessions = []
    await _setup(hass, mock_config_entry)
    assert _players(hass) == []

    silo.sessions = [data.movie_session()]
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=11), fire_all=True
    )
    await hass.async_block_till_done()

    assert _player_for(hass, "tristan").state == "playing"


async def test_known_client_comes_back_idle(hass, silo, mock_config_entry):
    """A registered client keeps its entity across a restart."""
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "media_player",
        "silo",
        f"{INSTALLATION_ID}:v1:7:silo_web:macos",
        suggested_object_id="silo_tristan",
        config_entry=mock_config_entry,
    )
    silo.sessions = []

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("media_player.silo_tristan")
    assert state is not None
    assert state.state == "idle"


async def test_watching_sensor_and_statistics(hass, silo, mock_config_entry):
    """The Plex-style counters are exposed on the server device."""
    silo.sessions = [data.movie_session(), data.episode_session()]

    await _setup(hass, mock_config_entry)

    sensors = {
        entity_id: hass.states.get(entity_id)
        for entity_id in hass.states.async_entity_ids("sensor")
    }
    values = {entity_id: state.state for entity_id, state in sensors.items()}
    assert any(state == "2" for state in values.values())
    assert "800" in values.values()  # total_movies
    assert "120" in values.values()  # total_shows
    assert "4" in values.values()  # total_users


async def test_sensors_can_be_disabled(hass, silo, entry_factory):
    """The statistics sensors are optional."""
    silo.sessions = []
    entry = entry_factory(options={"enable_sensors": False})

    await _setup(hass, entry)

    # Only the now-playing counter is created.
    assert len(hass.states.async_entity_ids("sensor")) == 1


async def test_refused_key_starts_reauth(hass, silo, mock_config_entry):
    """A 401 on the session view triggers the reauthentication flow."""
    silo.sessions_status = 401
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_update_interval_option_is_applied(hass, silo, entry_factory):
    """The polling interval comes from the options."""
    entry = entry_factory(options={CONF_UPDATE_INTERVAL: 30})

    await _setup(hass, entry)

    coordinator = entry.runtime_data.coordinator
    assert coordinator.update_interval == timedelta(seconds=30)


async def test_versioned_entity_is_renamed(hass, silo, mock_config_entry):
    """A 0.1.0 entity named after the app build is renamed on setup."""
    payload = data.iphone_session()
    session = SiloSession.from_payload(payload)
    assert session is not None
    key = session.client_key
    unique_id = f"{INSTALLATION_ID}:{key}"

    mock_config_entry.add_to_hass(hass)
    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, f"{INSTALLATION_ID}:{key}")},
        name="Tristan · Silo iPhone 1.1.0 (build 68) (iOS)",
    )
    entities.async_get_or_create(
        "media_player",
        DOMAIN,
        unique_id,
        suggested_object_id="tristan_silo_iphone_1_1_0_build_68_ios",
        config_entry=mock_config_entry,
        device_id=device.id,
    )
    silo.sessions = [payload]

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert (
        entities.async_get_entity_id("media_player", DOMAIN, unique_id)
        == "media_player.tristan_silo_iphone_ios"
    )
    renamed = devices.async_get(device.id)
    assert renamed is not None
    assert renamed.name == "Tristan · Silo iPhone (iOS)"
    assert hass.states.get("media_player.tristan_silo_iphone_ios") is not None
