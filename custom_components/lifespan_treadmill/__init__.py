"""LifeSpan treadmill console (SC110 / Omni) over Bluetooth."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant

from .const import CONF_IDLE_INTERVAL, DEFAULT_IDLE_INTERVAL
from .coordinator import LifeSpanCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]

type LifeSpanConfigEntry = ConfigEntry[LifeSpanCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: LifeSpanConfigEntry) -> bool:
    address: str = entry.data[CONF_ADDRESS]
    coordinator = LifeSpanCoordinator(
        hass,
        address,
        entry.title,
        entry.options.get(CONF_IDLE_INTERVAL, DEFAULT_IDLE_INTERVAL),
    )
    entry.runtime_data = coordinator

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            coordinator.async_on_advertisement,
            bluetooth.BluetoothCallbackMatcher(address=address, connectable=True),
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(
        hass, coordinator.async_run(), f"lifespan_treadmill {address}"
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: LifeSpanConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: LifeSpanConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded
