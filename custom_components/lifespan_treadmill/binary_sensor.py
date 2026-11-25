"""Binary sensors for LifeSpan Treadmill."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LifeSpanConfigEntry
from .entity import LifeSpanEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LifeSpanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([LifeSpanRunning(entry.runtime_data)])


class LifeSpanRunning(LifeSpanEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "running")

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data.status is None:
            return None
        return self.coordinator.data.is_running
