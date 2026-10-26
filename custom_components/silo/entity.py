"""Base entities shared by the Silo platforms."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from yarl import URL

from .const import DOMAIN, MANUFACTURER
from .coordinator import SiloCoordinator


class SiloEntity(CoordinatorEntity[SiloCoordinator]):
    """Coordinator-backed entity belonging to a Silo server."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: SiloCoordinator) -> None:
        """Initialize the entity and capture the server identity."""
        super().__init__(coordinator)
        self.server = coordinator.server

    @property
    def server_host(self) -> str:
        """Return the server host name, for diagnostics only."""
        return URL(self.server.url).host or MANUFACTURER


class SiloServerEntity(SiloEntity):
    """Entity attached to the Silo server device."""

    @property
    def device_info(self) -> DeviceInfo:
        """Describe the server device once, for the entity group."""
        # A short name keeps entity ids readable (``sensor.silo_watching``)
        # even when the entry points at a long in-cluster host name; the URL is
        # exposed as the device's configuration link instead.
        return DeviceInfo(
            identifiers={(DOMAIN, self.server.installation_id)},
            name=MANUFACTURER,
            manufacturer=MANUFACTURER,
            model="Silo server",
            sw_version=self.server.version,
            configuration_url=self.server.url,
        )
