"""Sensors for LifeSpan Treadmill."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfLength, UnitOfSpeed, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LifeSpanConfigEntry
from .const import CONF_UNIT, DEFAULT_UNIT, UNIT_KMH
from .entity import LifeSpanEntity
from .protocol import STATUS_NAMES, Readout


@dataclass(frozen=True, kw_only=True)
class LifeSpanSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Readout], float | int | str | None]


def _descriptions(metric: bool) -> tuple[LifeSpanSensorDescription, ...]:
    return (
        LifeSpanSensorDescription(
            key="status",
            translation_key="status",
            device_class=SensorDeviceClass.ENUM,
            options=[*STATUS_NAMES.values(), "unknown"],
            value_fn=lambda r: r.status_name,
        ),
        LifeSpanSensorDescription(
            key="speed",
            device_class=SensorDeviceClass.SPEED,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=(
                UnitOfSpeed.KILOMETERS_PER_HOUR if metric else UnitOfSpeed.MILES_PER_HOUR
            ),
            suggested_display_precision=1,
            # The console keeps reporting the last speed while stopped.
            value_fn=lambda r: r.speed if r.is_running else (0 if r.status is not None else None),
        ),
        LifeSpanSensorDescription(
            key="distance",
            device_class=SensorDeviceClass.DISTANCE,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=(
                UnitOfLength.KILOMETERS if metric else UnitOfLength.MILES
            ),
            suggested_display_precision=2,
            value_fn=lambda r: r.distance,
        ),
        LifeSpanSensorDescription(
            key="steps",
            translation_key="steps",
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement="steps",
            value_fn=lambda r: r.steps,
        ),
        LifeSpanSensorDescription(
            key="session_time",
            translation_key="session_time",
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.SECONDS,
            suggested_unit_of_measurement=UnitOfTime.MINUTES,
            value_fn=lambda r: r.duration_s,
        ),
        LifeSpanSensorDescription(
            key="calories",
            translation_key="calories",
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement="kcal",
            value_fn=lambda r: r.calories,
        ),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LifeSpanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    metric = entry.options.get(CONF_UNIT, DEFAULT_UNIT) == UNIT_KMH
    coordinator = entry.runtime_data
    async_add_entities(
        LifeSpanSensor(coordinator, d) for d in _descriptions(metric)
    )


class LifeSpanSensor(LifeSpanEntity, SensorEntity):
    entity_description: LifeSpanSensorDescription

    def __init__(self, coordinator, description: LifeSpanSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self):
        raw = self.coordinator.data.raw.get(self.entity_description.key)
        if self.entity_description.key == "session_time":
            raw = self.coordinator.data.raw.get("duration")
        return {"raw_frame": raw} if raw else None
