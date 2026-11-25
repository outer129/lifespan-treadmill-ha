"""Binary sensors for LifeSpan Treadmill."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LifeSpanConfigEntry
from .entity import LifeSpanEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LifeSpanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        [LifeSpanRunning(entry.runtime_data), LifeSpanConnected(entry.runtime_data)]
    )


class LifeSpanRunning(LifeSpanEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_translation_key = "running"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "running")

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data.status is None:
            return None
        return self.coordinator.data.is_running


class LifeSpanConnected(LifeSpanEntity, BinarySensorEntity):
    """Whether Home Assistant currently holds the BLE connection."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "connected")

    @property
    def available(self) -> bool:
        return True  # must report "off" rather than go unavailable

    @property
    def is_on(self) -> bool:
        return self.coordinator.connected

    @property
    def extra_state_attributes(self):
        return {"adapter": self.coordinator.source} if self.coordinator.source else None
