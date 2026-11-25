"""Sensors for LifeSpan Treadmill."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfLength, UnitOfSpeed,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LifeSpanConfigEntry
from .const import CONF_UNIT, DEFAULT_UNIT, UNIT_KMH
from .entity import LifeSpanEntity
from .protocol import STATUS_NAMES, Readout
from .session import Session

PARALLEL_UPDATES = 0


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
            state_class=SensorStateClass.TOTAL_INCREASING,
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
        [
            *(LifeSpanSensor(coordinator, d) for d in _descriptions(metric)),
            LifeSpanSignalStrength(coordinator),
            *(LifeSpanLastSessionSensor(coordinator, d) for d in _last_session(metric)),
        ]
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


class LifeSpanSignalStrength(LifeSpanEntity, SensorEntity):
    """RSSI of the last advertisement (diagnostic, disabled by default)."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "rssi")

    @property
    def available(self) -> bool:
        return self.coordinator.rssi is not None

    @property
    def native_value(self) -> int | None:
        return self.coordinator.rssi


@dataclass(frozen=True, kw_only=True)
class LifeSpanLastSessionDescription(SensorEntityDescription):
    session_fn: Callable[[Session], float | int | object]


def _last_session(metric: bool) -> tuple[LifeSpanLastSessionDescription, ...]:
    return (
        LifeSpanLastSessionDescription(
            key="last_session_ended",
            translation_key="last_session_ended",
            device_class=SensorDeviceClass.TIMESTAMP,
            session_fn=lambda s: s.ended,
        ),
        LifeSpanLastSessionDescription(
            key="last_session_duration",
            translation_key="last_session_duration",
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.SECONDS,
            suggested_unit_of_measurement=UnitOfTime.MINUTES,
            suggested_display_precision=0,
            session_fn=lambda s: s.duration_s,
        ),
        LifeSpanLastSessionDescription(
            key="last_session_steps",
            translation_key="last_session_steps",
            native_unit_of_measurement="steps",
            session_fn=lambda s: s.steps,
        ),
        LifeSpanLastSessionDescription(
            key="last_session_distance",
            translation_key="last_session_distance",
            device_class=SensorDeviceClass.DISTANCE,
            native_unit_of_measurement=(
                UnitOfLength.KILOMETERS if metric else UnitOfLength.MILES
            ),
            suggested_display_precision=2,
            session_fn=lambda s: s.distance,
        ),
        LifeSpanLastSessionDescription(
            key="last_session_calories",
            translation_key="last_session_calories",
            native_unit_of_measurement="kcal",
            session_fn=lambda s: s.calories,
        ),
        LifeSpanLastSessionDescription(
            key="last_session_average_speed",
            translation_key="last_session_average_speed",
            device_class=SensorDeviceClass.SPEED,
            native_unit_of_measurement=(
                UnitOfSpeed.KILOMETERS_PER_HOUR if metric else UnitOfSpeed.MILES_PER_HOUR
            ),
            suggested_display_precision=1,
            session_fn=lambda s: s.average_speed,
        ),
    )


class LifeSpanLastSessionSensor(LifeSpanEntity, RestoreSensor):
    """A value from the most recent completed session; survives restarts."""

    entity_description: LifeSpanLastSessionDescription

    def __init__(self, coordinator, description: LifeSpanLastSessionDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return True  # history of a past session doesn't depend on the link

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.coordinator.last_session is not None:
            self._on_session(self.coordinator.last_session, write=False)
        elif (last := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = last.native_value
        self.async_on_remove(
            self.coordinator.async_add_session_listener(self._on_session)
        )

    @callback
    def _on_session(self, session: Session, write: bool = True) -> None:
        self._attr_native_value = self.entity_description.session_fn(session)
        if write:
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Polled readouts don't change a finished session."""
