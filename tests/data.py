"""Payload builders mirroring Silo's v2 contract.

The shapes follow ``contracts/api/v2/fixtures/`` of Silo-Server/silo-server at
commit 8cbc8202 (build 1727), with values filled in so assertions stay readable.
"""

from __future__ import annotations

from typing import Any

from .const import INSTALLATION_ID

WEB_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
)
TV_USER_AGENT = "Silo/1.4.2 (AppleTV; tvOS 26.0)"


def system_info_payload(api_major: int = 2) -> dict[str, Any]:
    """Return the public server identity document."""
    return {
        "server_version": "8cbc8202",
        "api_major": api_major,
        "contract_digest": "3b8f0c2d9e1a4f6b",
        "links": {"openapi": "/api/v2/openapi.json"},
    }


def playback_capabilities_payload(
    installation_id: str = INSTALLATION_ID,
) -> dict[str, Any]:
    """Return the playback capability document carrying the installation id."""
    return {
        "installation_id": installation_id,
        "revision": "1",
        "state": "available",
        "allowed": True,
        "protocol_versions": [3],
        "features": ["sequenced_progress_v1"],
        "deliveries": [],
    }


def session_capabilities_payload(available: bool = True) -> dict[str, Any]:
    """Return the administrator session capability document."""
    return {
        "available": available,
        "state": "available" if available else "not_configured",
        "allowed": True,
        "user_filter": True,
        "summary": True,
        "node_observations": True,
        "effective_play_method": True,
        "effective_play_method_values": [
            "direct",
            "remux",
            "direct_stream",
            "transcode",
        ],
        "is_jellyfin_client": True,
        "transcode_hw_accel": True,
        "tone_map_mode": True,
        "tone_map_mode_values": ["auto", "always", "never"],
        "client_build": True,
        "client_channel": True,
        "target_audio_channels": True,
        "network_access_route": True,
        "stream_location": True,
        "node_routing": True,
        "output_format": True,
        "source_video_height": True,
        "revision": "1",
    }


DEFAULT_ACTIONS = ["pause", "resume", "stop", "message", "terminate"]


def command_capabilities_payload(
    actions: list[str] | None = None,
) -> dict[str, Any]:
    """Return the administrator command capability document."""
    return {
        "available": True,
        "state": "available",
        "allowed": True,
        "actions": list(actions if actions is not None else DEFAULT_ACTIONS),
        "sequenced_commands": True,
        "terminate_revokes_authority": True,
        "revision": "1",
    }


def stats_payload() -> dict[str, Any]:
    """Return the dashboard statistics document."""
    return {
        "total_items": 1200,
        "total_files": 1300,
        "total_users": 4,
        "total_movies": 800,
        "total_movie_files": 850,
        "total_shows": 120,
        "total_show_files": 450,
        "advisory_titles": 12,
        "active_streams": 1,
        "total_storage_bytes": 10_000_000_000_000,
        "watch_providers": [],
    }


def movie_session(**overrides: Any) -> dict[str, Any]:
    """Return a direct-play movie session from the web client on macOS."""
    payload: dict[str, Any] = {
        "session_id": "10",
        "user_id": "7",
        "username": "tristan",
        "profile_id": "1",
        "profile_name": "Tristan",
        "media_file_id": "44",
        "requested_media_file_id": "44",
        "content_id": "9001",
        "media_title": "Dune: Deuxième partie",
        "media_type": "movie",
        "poster_url": "/api/v2/images/poster/abc.jpg?exp=1&sig=x",
        "play_method": "direct",
        "effective_play_method": "direct",
        "reporting_node": "silo-0",
        "node_display_name": "silo-worker-0",
        "file_duration": 9300,
        "started_at": "2026-10-26T20:00:00.000Z",
        "updated_at": "2026-10-26T20:35:10.500Z",
        "position_seconds": 2110.5,
        "is_paused": False,
        "has_playback_control": True,
        "client_ip": "10.10.10.50",
        "stream_location": "local",
        "client_name": "Silo Web",
        "client_version": "1.4.2",
        "client_build": "1727",
        "client_channel": "release",
        "client_label": "Silo Web 1.4.2",
        "client_user_agent": WEB_USER_AGENT,
        "audio_track_index": 0,
        "transcode_audio": False,
        "stream_bitrate_kbps": 18_000,
        "target_bitrate_kbps": None,
        "source_bitrate_kbps": 18_000,
        "source_video_codec": "hevc",
        "source_video_resolution": "2160p",
        "source_video_height": 2160,
        "source_audio_codec": "eac3",
        "source_audio_channels": 6,
        "output_container": "mkv",
        "output_protocol": "http",
    }
    payload.update(overrides)
    return payload


def episode_session(**overrides: Any) -> dict[str, Any]:
    """Return a paused, transcoded episode session from an Apple TV."""
    payload = movie_session(
        session_id="11",
        user_id="8",
        username="pauline",
        profile_id="2",
        profile_name="Pauline",
        media_file_id="45",
        requested_media_file_id="46",
        content_id="9100",
        media_title="Severance",
        media_type="episode",
        series_name="Severance",
        episode_name="Qui est vivant ?",
        season_number=2,
        episode_number=3,
        poster_url="/api/v2/images/poster/def.jpg",
        play_method="transcode",
        effective_play_method="transcode",
        transcode_hw_accel="qsv",
        file_duration=3120,
        position_seconds=420.0,
        is_paused=True,
        client_ip="10.10.10.51",
        stream_location="remote",
        client_name="Silo",
        client_version="1.4.2",
        client_label="Silo 1.4.2",
        client_user_agent=TV_USER_AGENT,
        stream_bitrate_kbps=4_000,
        target_bitrate_kbps=4_000,
        source_bitrate_kbps=25_000,
        target_resolution="1080p",
        target_video_codec="h264",
        target_audio_codec="aac",
        target_audio_channels=2,
        source_video_resolution="2160p",
        source_audio_channels=8,
    )
    payload.update(overrides)
    return payload


def sessions_payload(
    items: list[dict[str, Any]],
    *,
    has_more: bool = False,
    next_cursor: str | None = None,
) -> dict[str, Any]:
    """Wrap session rows in the bounded collection envelope."""
    page: dict[str, Any] = {"has_more": has_more}
    if next_cursor is not None:
        page["next_cursor"] = next_cursor
    return {"items": items, "page": page}


def receipt_payload(
    command_id: str, sequence: int, *, outcome: str = "applied"
) -> dict[str, Any]:
    """Return the sequenced command receipt."""
    return {
        "command_id": command_id,
        "sequence": sequence,
        "outcome": outcome,
        "delivery": "dispatched",
    }
