"""Config flow for LifeSpan Treadmill."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
)

from .const import (
    CONF_IDLE_INTERVAL,
    CONF_UNIT,
    DEFAULT_IDLE_INTERVAL,
    DEFAULT_UNIT,
    DOMAIN,
    UNIT_KMH,
    UNIT_MPH,
)

UNIT_SELECTOR = SelectSelector(SelectSelectorConfig(options=[UNIT_MPH, UNIT_KMH]))


def _is_lifespan(info: BluetoothServiceInfoBleak) -> bool:
    return bool(info.name) and info.name.startswith("LifeSpan") and info.connectable


class LifeSpanConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._candidates: dict[str, str] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovery is not None
        if user_input is not None:
            return self._create(self._discovery.address, self._discovery.name, user_input)
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._discovery.name},
            data_schema=vol.Schema(
                {vol.Required(CONF_UNIT, default=DEFAULT_UNIT): UNIT_SELECTOR}
            ),
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self._create(address, self._candidates[address], user_input)

        configured = self._async_current_ids(include_ignore=False)
        for info in async_discovered_service_info(self.hass, connectable=True):
            if info.address not in configured and _is_lifespan(info):
                self._candidates[info.address] = info.name
        if not self._candidates:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {a: f"{n} ({a})" for a, n in self._candidates.items()}
                    ),
                    vol.Required(CONF_UNIT, default=DEFAULT_UNIT): UNIT_SELECTOR,
                }
            ),
        )

    def _create(self, address: str, name: str, user_input: dict[str, Any]) -> ConfigFlowResult:
        return self.async_create_entry(
            title=name or "LifeSpan Treadmill",
            data={CONF_ADDRESS: address},
            options={
                CONF_UNIT: user_input.get(CONF_UNIT, DEFAULT_UNIT),
                CONF_IDLE_INTERVAL: DEFAULT_IDLE_INTERVAL,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return LifeSpanOptionsFlow()


class LifeSpanOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            user_input[CONF_IDLE_INTERVAL] = int(user_input[CONF_IDLE_INTERVAL])
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UNIT, default=opts.get(CONF_UNIT, DEFAULT_UNIT)
                    ): UNIT_SELECTOR,
                    vol.Required(
                        CONF_IDLE_INTERVAL,
                        default=opts.get(CONF_IDLE_INTERVAL, DEFAULT_IDLE_INTERVAL),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=2, max=300, step=1, mode=NumberSelectorMode.BOX,
                            unit_of_measurement="s",
                        )
                    ),
                }
            ),
        )
