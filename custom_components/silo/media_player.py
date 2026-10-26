"""Media players for Silo playback clients.

Silo's administrator view reports live playback sessions, not devices: one
entity is created per (account, client name, platform) triple and kept as
``idle`` between playbacks, the way the Plex integration keeps one entity per
client. The control surface is the administrator command API only: pause,
resume, stop, terminate and a player message.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import Any, Final

from homeassistant.components.media_player import (
    DOMAIN as MEDIA_PLAYER_DOMAIN,
)
from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    ACTION_MESSAGE,
    ACTION_PAUSE,
    ACTION_RESUME,
    ACTION_STOP,
    ACTION_TERMINATE,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import SiloCoordinator, SiloRuntimeData
from .entity import SiloEntity
from .models import SiloSession
from .services import (
    SEND_MESSAGE_SCHEMA,
    SERVICE_SEND_MESSAGE,
    SERVICE_TERMINATE_SESSION,
    TERMINATE_SESSION_SCHEMA,
    async_dispatch_command,
)

_LOGGER = logging.getLogger(__name__)

# Silo media types mapped onto Home Assistant's media types.
_CONTENT_TYPES: Final[dict[str, MediaType]] = {
    "movie": MediaType.MOVIE,
    "episode": MediaType.EPISODE,
    "series": MediaType.TVSHOW,
    "season": MediaType.SEASON,
    "track": MediaType.TRACK,
    "song": MediaType.TRACK,
    "audio": MediaType.MUSIC,
    "album": MediaType.ALBUM,
    "artist": MediaType.ARTIST,
    "audiobook": MediaType.MUSIC,
    "podcast": MediaType.PODCAST,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one media player per Silo playback client."""
    runtime: SiloRuntimeData = entry.runtime_data
    coordinator = runtime.coordinator

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SEND_MESSAGE, SEND_MESSAGE_SCHEMA, "async_send_message"
    )
    platform.async_register_entity_service(
        SERVICE_TERMINATE_SESSION,
        TERMINATE_SESSION_SCHEMA,
        "async_terminate_session",
    )

    entities: dict[str, SiloMediaPlayer] = {}
    for key in _registered_client_keys(hass, entry, runtime):
        entities[key] = SiloMediaPlayer(coordinator, key)
    if entities:
        async_add_entities(list(entities.values()))

    @callback
    def _async_add_missing_entities() -> None:
        """Add entities for clients that started playing since the last poll."""
        data = coordinator.data
        if data is None:
            return
        new_entities: list[SiloMediaPlayer] = []
        for key in data.sessions_by_key:
            if key in entities:
                continue
            entity = SiloMediaPlayer(coordinator, key)
            entities[key] = entity
            new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities)

    _async_add_missing_entities()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_missing_entities))


def _registered_client_keys(
    hass: HomeAssistant, entry: ConfigEntry, runtime: SiloRuntimeData
) -> Iterable[str]:
    """Return the client keys this entry already registered.

    Entities survive a Home Assistant restart as idle players, so an automation
    targeting one of them does not break until the next playback.
    """
    prefix = f"{runtime.server.installation_id}:"
    registry = er.async_get(hass)
    keys: list[str] = []
    for registry_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if registry_entry.domain != MEDIA_PLAYER_DOMAIN:
            continue
        if registry_entry.platform != DOMAIN:
            continue
        unique_id = registry_entry.unique_id or ""
        if not unique_id.startswith(prefix):
            continue
        key = unique_id[len(prefix) :]
        if key:
            keys.append(key)
    return keys


class SiloMediaPlayer(SiloEntity, MediaPlayerEntity):
    """One Silo playback client."""

    _attr_name = None

    def __init__(self, coordinator: SiloCoordinator, key: str) -> None:
        """Initialize the player for a client key."""
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{coordinator.server.installation_id}:{key}"

    @property
    def session(self) -> SiloSession | None:
        """Return the session currently held by this client, if any."""
        data = self.coordinator.data
        if data is None:
            return None
        return data.sessions_by_key.get(self._key)

    @property
    def device_info(self) -> DeviceInfo:
        """Describe the client device once a session names it."""
        identifiers = {(DOMAIN, self._attr_unique_id or self._key)}
        session = self.session
        if session is None:
            # A restored entity keeps its existing device untouched.
            return DeviceInfo(identifiers=identifiers)
        return DeviceInfo(
            identifiers=identifiers,
            name=session.display_name,
            manufacturer=MANUFACTURER,
            model=session.platform_label or session.client_name,
            sw_version=session.client_version,
        )

    @property
    def state(self) -> MediaPlayerState:
        """Return the playback state of this client."""
        session = self.session
        if session is None:
            return MediaPlayerState.IDLE
        if session.is_paused:
            return MediaPlayerState.PAUSED
        return MediaPlayerState.PLAYING

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Advertise the commands this server actually dispatches."""
        data = self.coordinator.data
        actions = data.command_actions if data is not None else frozenset()
        features = MediaPlayerEntityFeature(0)
        if ACTION_PAUSE in actions:
            features |= MediaPlayerEntityFeature.PAUSE
        if ACTION_RESUME in actions:
            features |= MediaPlayerEntityFeature.PLAY
        if ACTION_STOP in actions:
            features |= MediaPlayerEntityFeature.STOP
        return features

    @property
    def media_content_id(self) -> str | None:
        """Return the catalogue identifier of the playing media."""
        session = self.session
        if session is None:
            return None
        return session.content_id or session.media_file_id

    @property
    def media_content_type(self) -> str | None:
        """Return the media type, mapped onto Home Assistant's vocabulary."""
        session = self.session
        if session is None or not session.media_type:
            return None
        return str(_CONTENT_TYPES.get(session.media_type, session.media_type))

    @property
    def media_title(self) -> str | None:
        """Return the episode title, or the media title."""
        session = self.session
        return session.title if session is not None else None

    @property
    def media_series_title(self) -> str | None:
        """Return the series title for an episode."""
        session = self.session
        return session.series_name if session is not None else None

    @property
    def media_season(self) -> int | None:
        """Return the season number for an episode."""
        session = self.session
        if session is None or not session.series_name:
            return None
        return session.season_number

    @property
    def media_episode(self) -> int | None:
        """Return the episode number for an episode."""
        session = self.session
        if session is None or not session.series_name:
            return None
        return session.episode_number

    @property
    def media_duration(self) -> int | None:
        """Return the duration of the playing file, in seconds."""
        session = self.session
        return session.file_duration if session is not None else None

    @property
    def media_position(self) -> float | None:
        """Return the last reported position, in seconds."""
        session = self.session
        return session.position_seconds if session is not None else None

    @property
    def media_position_updated_at(self):
        """Return when the position was reported, so HA can extrapolate."""
        session = self.session
        return session.updated_at if session is not None else None

    @property
    def media_image_url(self) -> str | None:
        """Return the (presigned) poster of the playing media."""
        session = self.session
        if session is None:
            return None
        return session.poster_url_absolute(self.server.url)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Expose the Silo playback details the Plex integration has no name for."""
        session = self.session
        if session is None:
            return {}
        attributes: dict[str, Any] = {}
        for key, value in (
            ("session_id", session.session_id),
            ("username", session.username),
            ("profile_name", session.profile_name),
            ("client_label", session.client_label),
            ("client_label_full", session.client_label_full),
            ("client_ip", session.client_ip),
            ("client_user_agent", session.client_user_agent),
            ("client_version", session.client_version),
            ("platform", session.platform_label),
            ("play_method", session.play_method),
            ("effective_play_method", session.effective_play_method),
            ("stream_location", session.stream_location),
            ("node_display_name", session.node_display_name),
            ("transcode_hw_accel", session.transcode_hw_accel),
            ("source_video_codec", session.source_video_codec),
            ("source_video_resolution", session.source_video_resolution),
            ("source_audio_codec", session.source_audio_codec),
            ("source_audio_channels", session.source_audio_channels),
            ("source_bitrate_kbps", session.source_bitrate_kbps),
            ("stream_bitrate_kbps", session.stream_bitrate_kbps),
            ("target_video_codec", session.target_video_codec),
            ("target_resolution", session.target_resolution),
            ("target_audio_codec", session.target_audio_codec),
            ("target_audio_channels", session.target_audio_channels),
            ("target_bitrate_kbps", session.target_bitrate_kbps),
            ("output_container", session.output_container),
            ("output_protocol", session.output_protocol),
            ("has_playback_control", session.has_playback_control),
            ("is_jellyfin_client", session.is_jellyfin_client),
            (
                "started_at",
                session.started_at.isoformat() if session.started_at else None,
            ),
            (
                "updated_at",
                session.updated_at.isoformat() if session.updated_at else None,
            ),
        ):
            if value is not None:
                attributes[key] = value
        return attributes

    async def _async_send(self, action: str, **kwargs: Any) -> None:
        """Dispatch a command on the session this client currently holds."""
        session = self.session
        if session is None:
            raise HomeAssistantError(
                "Silo: this client has no playback session to control"
            )
        await async_dispatch_command(
            self.coordinator, session.session_id, action, **kwargs
        )

    async def async_media_play(self) -> None:
        """Resume playback."""
        await self._async_send(ACTION_RESUME)

    async def async_media_pause(self) -> None:
        """Pause playback."""
        await self._async_send(ACTION_PAUSE)

    async def async_media_stop(self) -> None:
        """Stop playback."""
        await self._async_send(ACTION_STOP)

    async def async_send_message(
        self, message: str, title: str | None = None, reason: str | None = None
    ) -> None:
        """Display a message on the client's player."""
        if not message:
            raise HomeAssistantError("Silo: the message cannot be empty")
        await self._async_send(
            ACTION_MESSAGE,
            message=message,
            title=title,
            reason=reason,
        )

    async def async_terminate_session(self, reason: str | None = None) -> None:
        """Revoke the session's playback authority."""
        await self._async_send(ACTION_TERMINATE, reason=reason)
