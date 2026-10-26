"""Typed views over the Silo playback session payload.

Silo's administrator session rows are an observation, not a control receipt:
they carry no device identifier, and ``client_label`` embeds the client
version. Entity identity therefore has to be derived, and this module owns that
derivation so it can be tested without Home Assistant.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

# Bumped when the derivation changes, so unique ids stay stable across releases.
KEY_VERSION: Final = 1

_PLATFORM_TOKENS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("appletv", ("appletv", "tvos", "apple tv")),
    ("ios", ("iphone", "ipad", "ipados", "crios/", "fxios/")),
    ("chromeos", ("cros ",)),
    ("android", ("android",)),
    ("webos", ("webos", "web0s")),
    ("tizen", ("tizen", "samsungbrowser")),
    ("roku", ("roku",)),
    ("firetv", ("firetv", "aftb", "aftm", "afts", "aftt", "silk/")),
    ("playstation", ("playstation", "ps4", "ps5")),
    ("xbox", ("xbox",)),
    ("macos", ("macintosh", "mac os", "macos", "darwin")),
    ("windows", ("windows nt", "windows")),
    ("linux", ("linux", "x11")),
)

PLATFORM_LABELS: Final[dict[str, str]] = {
    "appletv": "Apple TV",
    "ios": "iOS",
    "chromeos": "ChromeOS",
    "android": "Android",
    "webos": "webOS",
    "tizen": "Tizen",
    "roku": "Roku",
    "firetv": "Fire TV",
    "playstation": "PlayStation",
    "xbox": "Xbox",
    "macos": "macOS",
    "windows": "Windows",
    "linux": "Linux",
}

_VERSION_SUFFIX: Final = re.compile(r"\s+v?\d+(?:\.\d+)+\s*$")


def _text(data: Mapping[str, Any], key: str) -> str | None:
    """Return a stripped string field, or None when absent/empty."""
    value = data.get(key)
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return None


def _int(data: Mapping[str, Any], key: str) -> int | None:
    """Return an integer field, or None when absent/incompatible."""
    value = data.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _float(data: Mapping[str, Any], key: str) -> float | None:
    """Return a float field, or None when absent/incompatible."""
    value = data.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _bool(data: Mapping[str, Any], key: str) -> bool:
    """Return a boolean field, defaulting to False."""
    return data.get(key) is True


def _instant(data: Mapping[str, Any], key: str) -> datetime | None:
    """Return an RFC 3339 instant as an aware UTC datetime."""
    value = data.get(key)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _slug(value: str) -> str:
    """Reduce a free-form label to a stable identifier fragment."""
    slug = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return slug or "client"


def strip_version(label: str) -> str:
    """Drop a trailing version so a client update does not rename an entity."""
    stripped = _VERSION_SUFFIX.sub("", label).strip()
    return stripped or label


@dataclass(frozen=True, slots=True)
class SiloSession:
    """One live playback session as the administrator API reports it."""

    session_id: str
    user_id: str
    username: str | None = None
    profile_id: str | None = None
    profile_name: str | None = None
    media_file_id: str | None = None
    content_id: str | None = None
    media_title: str | None = None
    media_type: str | None = None
    series_name: str | None = None
    episode_name: str | None = None
    season_number: int | None = None
    episode_number: int | None = None
    poster_url: str | None = None
    position_seconds: float = 0.0
    file_duration: int | None = None
    is_paused: bool = False
    has_playback_control: bool = False
    client_name: str | None = None
    client_label: str | None = None
    client_label_full: str | None = None
    client_version: str | None = None
    client_build: str | None = None
    client_channel: str | None = None
    client_ip: str | None = None
    client_user_agent: str | None = None
    play_method: str | None = None
    effective_play_method: str | None = None
    stream_location: str | None = None
    node_display_name: str | None = None
    transcode_hw_accel: str | None = None
    stream_bitrate_kbps: int | None = None
    target_bitrate_kbps: int | None = None
    source_bitrate_kbps: int | None = None
    source_video_codec: str | None = None
    source_video_resolution: str | None = None
    source_video_height: int | None = None
    source_audio_codec: str | None = None
    source_audio_channels: int | None = None
    target_video_codec: str | None = None
    target_resolution: str | None = None
    target_audio_codec: str | None = None
    target_audio_channels: int | None = None
    output_container: str | None = None
    output_protocol: str | None = None
    is_jellyfin_client: bool = False
    started_at: datetime | None = None
    updated_at: datetime | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> SiloSession | None:
        """Build a session, returning None when the payload names no session."""
        session_id = _text(data, "session_id")
        user_id = _text(data, "user_id")
        if not session_id or not user_id:
            return None
        return cls(
            session_id=session_id,
            user_id=user_id,
            username=_text(data, "username"),
            profile_id=_text(data, "profile_id"),
            profile_name=_text(data, "profile_name"),
            media_file_id=_text(data, "media_file_id"),
            content_id=_text(data, "content_id"),
            media_title=_text(data, "media_title"),
            media_type=_text(data, "media_type"),
            series_name=_text(data, "series_name"),
            episode_name=_text(data, "episode_name"),
            season_number=_int(data, "season_number"),
            episode_number=_int(data, "episode_number"),
            poster_url=_text(data, "poster_url"),
            position_seconds=_float(data, "position_seconds") or 0.0,
            file_duration=_int(data, "file_duration"),
            is_paused=_bool(data, "is_paused"),
            has_playback_control=_bool(data, "has_playback_control"),
            client_name=_text(data, "client_name"),
            client_label=_text(data, "client_label"),
            client_label_full=_text(data, "client_label_full"),
            client_version=_text(data, "client_version"),
            client_build=_text(data, "client_build"),
            client_channel=_text(data, "client_channel"),
            client_ip=_text(data, "client_ip"),
            client_user_agent=_text(data, "client_user_agent"),
            play_method=_text(data, "play_method"),
            effective_play_method=_text(data, "effective_play_method"),
            stream_location=_text(data, "stream_location"),
            node_display_name=_text(data, "node_display_name"),
            transcode_hw_accel=_text(data, "transcode_hw_accel"),
            stream_bitrate_kbps=_int(data, "stream_bitrate_kbps"),
            target_bitrate_kbps=_int(data, "target_bitrate_kbps"),
            source_bitrate_kbps=_int(data, "source_bitrate_kbps"),
            source_video_codec=_text(data, "source_video_codec"),
            source_video_resolution=_text(data, "source_video_resolution"),
            source_video_height=_int(data, "source_video_height"),
            source_audio_codec=_text(data, "source_audio_codec"),
            source_audio_channels=_int(data, "source_audio_channels"),
            target_video_codec=_text(data, "target_video_codec"),
            target_resolution=_text(data, "target_resolution"),
            target_audio_codec=_text(data, "target_audio_codec"),
            target_audio_channels=_int(data, "target_audio_channels"),
            output_container=_text(data, "output_container"),
            output_protocol=_text(data, "output_protocol"),
            is_jellyfin_client=_bool(data, "is_jellyfin_client"),
            started_at=_instant(data, "started_at"),
            updated_at=_instant(data, "updated_at"),
            raw=dict(data),
        )

    @property
    def platform(self) -> str:
        """Classify the client platform from the user agent and labels."""
        haystack = " ".join(
            part
            for part in (
                self.client_user_agent,
                self.client_label_full,
                self.client_label,
                self.client_name,
            )
            if part
        ).casefold()
        for platform, tokens in _PLATFORM_TOKENS:
            if any(token in haystack for token in tokens):
                return platform
        if self.client_user_agent:
            digest = hashlib.sha1(
                self.client_user_agent.encode(), usedforsecurity=False
            ).hexdigest()
            return digest[:8]
        return "unknown"

    @property
    def platform_label(self) -> str | None:
        """Return a human readable platform, when one was recognized."""
        return PLATFORM_LABELS.get(self.platform)

    @property
    def client_key(self) -> str:
        """Return the stable identity of the client that holds this session."""
        name = self.client_name or self.client_label or "Silo"
        return f"v{KEY_VERSION}:{self.user_id}:{_slug(name)}:{self.platform}"

    @property
    def display_name(self) -> str:
        """Return the entity name: who is watching, where."""
        core = strip_version(
            self.client_label_full or self.client_label or self.client_name or "Silo"
        )
        platform = self.platform_label
        if platform:
            core = f"{core} ({platform})"
        if self.username:
            return f"{self.username} · {core}"
        return core

    @property
    def title(self) -> str | None:
        """Return the episode title when there is one, else the media title."""
        return self.episode_name or self.media_title

    @property
    def poster_path(self) -> str | None:
        """Return the poster reference as the server reported it."""
        return self.poster_url

    def poster_url_absolute(self, base_url: str) -> str | None:
        """Absolutize the (presigned) poster reference against the server URL."""
        if not self.poster_url:
            return None
        if self.poster_url.startswith(("http://", "https://")):
            return self.poster_url
        if self.poster_url.startswith("/"):
            return f"{base_url.rstrip('/')}{self.poster_url}"
        return None


@dataclass(frozen=True, slots=True)
class SiloServerInfo:
    """Identity of the server a config entry talks to."""

    installation_id: str
    version: str | None
    url: str


@dataclass(frozen=True, slots=True)
class SiloSnapshot:
    """One poll of the server."""

    sessions: tuple[SiloSession, ...]
    sessions_by_key: dict[str, SiloSession]
    command_actions: frozenset[str]
    stats: Mapping[str, Any] | None = None

    @classmethod
    def build(
        cls,
        sessions: list[SiloSession],
        command_actions: frozenset[str],
        stats: Mapping[str, Any] | None = None,
    ) -> SiloSnapshot:
        """Index sessions by client key, keeping the most recent one per key."""
        by_key: dict[str, SiloSession] = {}
        for session in sessions:
            current = by_key.get(session.client_key)
            if current is None or _is_newer(session, current):
                by_key[session.client_key] = session
        return cls(
            sessions=tuple(sessions),
            sessions_by_key=by_key,
            command_actions=command_actions,
            stats=stats,
        )


def _is_newer(candidate: SiloSession, current: SiloSession) -> bool:
    """Tell which of two sessions sharing a client key started last."""
    if candidate.started_at and current.started_at:
        return candidate.started_at >= current.started_at
    return True
