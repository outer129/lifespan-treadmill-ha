"""Diagnostics download for LifeSpan Treadmill."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from . import LifeSpanConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LifeSpanConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "options": dict(entry.options),
        "connected": coordinator.connected,
        "adapter": coordinator.source,
        "rssi": coordinator.rssi,
        "device_information": coordinator.device_information,
        "readout": asdict(coordinator.data),
        "last_update_success": coordinator.last_update_success,
    }
