"""Event entity fired when a walking session completes."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LifeSpanConfigEntry
from .const import CONF_UNIT, DEFAULT_UNIT, UNIT_KMH
from .entity import LifeSpanEntity
from .session import Session

PARALLEL_UPDATES = 0
EVENT_SESSION_COMPLETED = "session_completed"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LifeSpanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    metric = entry.options.get(CONF_UNIT, DEFAULT_UNIT) == UNIT_KMH
    async_add_entities([LifeSpanSessionEvent(entry.runtime_data, metric)])


class LifeSpanSessionEvent(LifeSpanEntity, EventEntity):
    _attr_translation_key = "session"
    _attr_event_types = [EVENT_SESSION_COMPLETED]

    def __init__(self, coordinator, metric: bool) -> None:
        super().__init__(coordinator, "session")
        self._distance_unit = "km" if metric else "mi"
        self._speed_unit = "km/h" if metric else "mph"

    @property
    def available(self) -> bool:
        return True  # an event entity has nothing to go stale

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_session_listener(self._on_session)
        )

    @callback
    def _on_session(self, s: Session) -> None:
        self._trigger_event(
            EVENT_SESSION_COMPLETED,
            {
                "started": s.started.isoformat(),
                "ended": s.ended.isoformat(),
                "duration_s": s.duration_s,
                "steps": s.steps,
                "distance": s.distance,
                "distance_unit": self._distance_unit,
                "calories": s.calories,
                "average_speed": s.average_speed,
                "speed_unit": self._speed_unit,
            },
        )
        self.async_write_ha_state()
