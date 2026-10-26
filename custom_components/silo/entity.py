"""Base entities shared by the Silo platforms."""

from __future__ import annotations

from urllib.parse import urlparse

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

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
        """Return the server host name, used as the device name."""
        return urlparse(self.server.url).hostname or MANUFACTURER


class SiloServerEntity(SiloEntity):
    """Entity attached to the Silo server device."""

    @property
    def device_info(self) -> DeviceInfo:
        """Describe the server device once, for the entity group."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.server.installation_id)},
            name=self.server_host,
            manufacturer=MANUFACTURER,
            model="Silo server",
            sw_version=self.server.version,
        )
