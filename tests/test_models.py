"""Tests for the session models."""

from __future__ import annotations

import re

import pytest
from custom_components.silo.models import SiloSession, SiloSnapshot

from . import data


def test_key_is_stable_across_client_versions():
    """A client update must not rename the entity."""
    first = SiloSession.from_payload(
        data.movie_session(client_version="1.4.2", client_label="Silo Web 1.4.2")
    )
    second = SiloSession.from_payload(
        data.movie_session(client_version="1.5.0", client_label="Silo Web 1.5.0")
    )

    assert first is not None
    assert second is not None
    assert first.client_key == second.client_key
    assert first.platform == "macos"
    assert first.display_name == "tristan · Silo Web (macOS)"


def test_two_accounts_never_share_an_entity():
    """The same device used by two accounts is two players."""
    first = SiloSession.from_payload(
        data.movie_session(user_id="7", username="tristan")
    )
    second = SiloSession.from_payload(
        data.movie_session(user_id="8", username="pauline")
    )

    assert first is not None
    assert second is not None
    assert first.client_key != second.client_key


@pytest.mark.parametrize(
    ("overrides", "platform"),
    [
        ({"client_user_agent": data.WEB_USER_AGENT}, "macos"),
        ({"client_user_agent": data.TV_USER_AGENT}, "appletv"),
        (
            {
                "client_user_agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 Version/26.0 Mobile/15E148 Safari/604.1"
                )
            },
            "ios",
        ),
        (
            {
                "client_user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "Chrome/142.0.0.0 Safari/537.36"
                )
            },
            "windows",
        ),
        (
            {
                "client_user_agent": (
                    "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 "
                    "Chrome/142.0.0.0 Mobile Safari/537.36"
                )
            },
            "android",
        ),
        ({"client_user_agent": "webOS.TV-2024/1.0"}, "webos"),
    ],
)
def test_platform_classification(overrides, platform):
    """The platform is derived from the user agent."""
    session = SiloSession.from_payload(data.movie_session(**overrides))

    assert session is not None
    assert session.platform == platform


def test_unknown_agent_keeps_a_stable_fragment():
    """An unrecognized client keeps a deterministic identity fragment."""
    session = SiloSession.from_payload(
        data.movie_session(
            client_user_agent="SomePlayer/2.0", client_label="SomePlayer 2.0"
        )
    )

    assert session is not None
    assert re.fullmatch(r"[0-9a-f]{8}", session.platform)
    assert session.platform_label is None


def test_missing_fields_are_tolerated():
    """Only the two identifiers are required."""
    session = SiloSession.from_payload({"session_id": "1", "user_id": "2"})

    assert session is not None
    assert session.media_title is None
    assert session.position_seconds == 0.0
    assert session.is_paused is False
    assert session.updated_at is None


def test_payload_without_identifiers_is_ignored():
    """A row with no session identity cannot drive an entity."""
    assert SiloSession.from_payload({"media_title": "Dune"}) is None


def test_instants_are_parsed_as_utc():
    """RFC 3339 instants keep their instant and gain a UTC zone."""
    session = SiloSession.from_payload(data.movie_session())

    assert session is not None
    assert session.updated_at is not None
    assert session.updated_at.isoformat() == "2026-10-26T20:35:10.500000+00:00"
    assert session.started_at is not None
    assert session.started_at.utcoffset().total_seconds() == 0


def test_poster_is_absolutized_against_the_server():
    """Relative presigned posters are resolved, absolute ones kept."""
    relative = SiloSession.from_payload(data.movie_session())
    absolute = SiloSession.from_payload(
        data.movie_session(poster_url="https://cdn.example/x.jpg")
    )
    missing = SiloSession.from_payload(data.movie_session(poster_url=None))

    assert relative is not None
    assert absolute is not None
    assert missing is not None
    assert (
        relative.poster_url_absolute("http://silo.test/")
        == "http://silo.test/api/v2/images/poster/abc.jpg?exp=1&sig=x"
    )
    assert (
        absolute.poster_url_absolute("http://silo.test") == "https://cdn.example/x.jpg"
    )
    assert missing.poster_url_absolute("http://silo.test") is None


def test_episode_title_prefers_the_episode_name():
    """Plex parity: media_title is the episode, media_series_title the show."""
    session = SiloSession.from_payload(data.episode_session())

    assert session is not None
    assert session.title == "Qui est vivant ?"
    assert session.series_name == "Severance"
    assert session.season_number == 2
    assert session.episode_number == 3


def test_snapshot_keeps_the_newest_session_per_client():
    """Two sessions on one client do not fight over the entity."""
    older = SiloSession.from_payload(
        data.movie_session(session_id="1", started_at="2026-10-26T20:00:00.000Z")
    )
    newer = SiloSession.from_payload(
        data.movie_session(session_id="2", started_at="2026-10-26T21:00:00.000Z")
    )

    assert older is not None
    assert newer is not None
    snapshot = SiloSnapshot.build([older, newer], frozenset({"pause"}))

    assert len(snapshot.sessions) == 2
    assert snapshot.sessions_by_key[older.client_key].session_id == "2"
    assert snapshot.command_actions == frozenset({"pause"})
