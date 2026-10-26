"""Sensors describing the Silo server."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SiloRuntimeData
from .entity import SiloServerEntity


@dataclass(frozen=True, kw_only=True)
class SiloStatsDescription(SensorEntityDescription):
    """Describe a dashboard statistic exposed as a sensor."""

    value_key: str


STATS_SENSORS: tuple[SiloStatsDescription, ...] = (
    SiloStatsDescription(
        key="movies",
        translation_key="movies",
        value_key="total_movies",
        icon="mdi:movie",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SiloStatsDescription(
        key="shows",
        translation_key="shows",
        value_key="total_shows",
        icon="mdi:television-classic",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SiloStatsDescription(
        key="files",
        translation_key="files",
        value_key="total_files",
        icon="mdi:file-multiple",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SiloStatsDescription(
        key="users",
        translation_key="users",
        value_key="total_users",
        icon="mdi:account-multiple",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SiloStatsDescription(
        key="storage",
        translation_key="storage",
        value_key="total_storage_bytes",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_display_precision=1,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the now-playing counter and, optionally, the library statistics."""
    runtime: SiloRuntimeData = entry.runtime_data
    entities: list[SensorEntity] = [SiloWatchingSensor(runtime)]
    if runtime.coordinator.sensors_enabled:
        entities.extend(
            SiloStatsSensor(runtime, description) for description in STATS_SENSORS
        )
    async_add_entities(entities)


class SiloWatchingSensor(SiloServerEntity, SensorEntity):
    """Number of live playback sessions Silo reports."""

    _attr_translation_key = "watching"
    _attr_icon = "mdi:play-circle-outline"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, runtime: SiloRuntimeData) -> None:
        """Initialize the counter for one server."""
        super().__init__(runtime.coordinator)
        self._attr_unique_id = f"{runtime.server.installation_id}:watching"

    @property
    def native_value(self) -> int:
        """Return the number of live sessions."""
        data = self.coordinator.data
        return len(data.sessions) if data is not None else 0


class SiloStatsSensor(SiloServerEntity, SensorEntity):
    """One dashboard statistic of the Silo server."""

    entity_description: SiloStatsDescription

    def __init__(
        self, runtime: SiloRuntimeData, description: SiloStatsDescription
    ) -> None:
        """Initialize the statistic sensor."""
        super().__init__(runtime.coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{runtime.server.installation_id}:{description.key}"

    @property
    def available(self) -> bool:
        """Only expose a value once the statistics were read."""
        data = self.coordinator.data
        return super().available and data is not None and data.stats is not None

    @property
    def native_value(self) -> float | int | None:
        """Return the statistic Silo reported."""
        data = self.coordinator.data
        if data is None or data.stats is None:
            return None
        value = data.stats.get(self.entity_description.value_key)
        if isinstance(value, int | float):
            return value
        return None
