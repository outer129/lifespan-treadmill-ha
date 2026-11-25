"""Base entity for LifeSpan Treadmill."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import LifeSpanCoordinator


class LifeSpanEntity(CoordinatorEntity[LifeSpanCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: LifeSpanCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            manufacturer=MANUFACTURER,
            model="Treadmill console (SC110 / Omni)",
            name=coordinator.device_name,
        )
