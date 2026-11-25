"""Integration-level tests against a real HA core (bluetooth stack mocked)."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.lifespan_treadmill.const import DOMAIN
from custom_components.lifespan_treadmill.coordinator import LifeSpanCoordinator
from custom_components.lifespan_treadmill.protocol import WRITE_CHAR_UUID

ADDR = "AA:BB:CC:DD:EE:FF"


def _service_info():
    dev = BLEDevice(ADDR, "LifeSpan-TM", None)
    return BluetoothServiceInfoBleak(
        name="LifeSpan-TM", address=ADDR, rssi=-60, manufacturer_data={},
        service_data={}, service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
        source="local", device=dev, advertisement=None, connectable=True,
        time=0, tx_power=None,
    )


async def test_bluetooth_discovery_flow(hass: HomeAssistant):
    hass.config.components.add("bluetooth_adapters")
    hass.config.components.add("bluetooth")
    with patch("custom_components.lifespan_treadmill.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=_service_info()
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "bluetooth_confirm"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"unit": "mph"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "LifeSpan-TM"
    assert result["data"] == {"address": ADDR}
    assert result["options"]["unit"] == "mph"
    with patch("custom_components.lifespan_treadmill.async_unload_entry", return_value=True):
        await hass.config_entries.async_unload(result["result"].entry_id)


class FakeConsole:
    """Simulates the SC110: answers each write with a notification."""

    def __init__(self, answers, drop=()):
        self.answers = answers
        self.drop = set(drop)
        self.is_connected = True
        self.cb = None
        self.writes = []
        self.services = MagicMock()
        self.services.get_characteristic.side_effect = (
            lambda uuid: MagicMock(uuid=uuid, properties=["write", "notify", "read"])
        )

    DIS = {
        "00002a24-0000-1000-8000-00805f9b34fb": b"SC110\x00",
        "00002a26-0000-1000-8000-00805f9b34fb": b"V1.2 ",
    }

    async def read_gatt_char(self, char):
        if char.uuid not in self.DIS:
            raise BleakError("not readable")
        return bytearray(self.DIS[char.uuid])

    async def start_notify(self, _char, cb):
        self.cb = cb

    async def write_gatt_char(self, uuid, data, response):
        assert uuid == WRITE_CHAR_UUID and len(data) == 6
        op = data[1]
        self.writes.append(op)
        if op in self.drop:
            return
        loop = asyncio.get_running_loop()
        loop.call_later(0.001, self.cb, None, bytearray(self.answers[op]))

    async def disconnect(self):
        self.is_connected = False


ANSWERS = {
    0x91: bytes.fromhex("a1aa03000000"),  # running
    0x82: bytes.fromhex("a1aa02140000"),  # 2.20
    0x88: bytes.fromhex("a1aa0f6e0000"),  # 3950
    0x85: bytes.fromhex("a1aa011f0000"),  # 1.31
    0x89: bytes.fromhex("a1aa01062d00"),  # 1:06:45
    0x87: bytes.fromhex("a1aa00eb0000"),  # 235
}


async def test_poll_loop_decodes(hass: HomeAssistant):
    coord = LifeSpanCoordinator(hass, MagicMock(), ADDR, "LifeSpan-TM", 10)
    fake = FakeConsole(ANSWERS)
    with patch(
        "custom_components.lifespan_treadmill.coordinator.establish_connection",
        return_value=fake,
    ), patch("custom_components.lifespan_treadmill.coordinator.ACTIVE_GAP", 0):
        task = asyncio.create_task(coord._connect_and_poll(MagicMock()))
        for _ in range(200):
            await asyncio.sleep(0.01)
            if coord.data.calories is not None:
                break
        fake.is_connected = False
        await asyncio.wait_for(task, 3)
    d = coord.data
    assert coord.last_update_success
    assert coord.device_information == {"model": "SC110", "firmware": "V1.2"}
    assert (d.status_name, d.speed, d.steps, d.distance, d.duration_s, d.calories) == (
        "running", 2.2, 3950, 1.31, 4005, 235
    )


async def test_unanswered_requests_force_reconnect(hass: HomeAssistant):
    coord = LifeSpanCoordinator(hass, MagicMock(), ADDR, "LifeSpan-TM", 10)
    fake = FakeConsole(ANSWERS, drop=set(ANSWERS))
    with patch(
        "custom_components.lifespan_treadmill.coordinator.establish_connection",
        return_value=fake,
    ), patch("custom_components.lifespan_treadmill.coordinator.RESPONSE_TIMEOUT", 0.01), patch(
        "custom_components.lifespan_treadmill.coordinator.LATE_REPLY_GRACE", 0
    ):
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(coord._connect_and_poll(MagicMock()), 3)


async def test_disconnect_mid_request_raises(hass: HomeAssistant):
    coord = LifeSpanCoordinator(hass, MagicMock(), ADDR, "LifeSpan-TM", 10)
    fake = FakeConsole(ANSWERS, drop={0x91})
    with patch(
        "custom_components.lifespan_treadmill.coordinator.establish_connection",
        return_value=fake,
    ):
        task = asyncio.create_task(coord._connect_and_poll(MagicMock()))
        await asyncio.sleep(0.05)
        coord._on_disconnect(fake)
        with pytest.raises(BleakError):
            await asyncio.wait_for(task, 3)


async def test_full_setup_registers_device_and_entities(hass: HomeAssistant):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from homeassistant.helpers import device_registry as dr, entity_registry as er

    hass.config.components.update({"bluetooth", "bluetooth_adapters"})
    entry = MockConfigEntry(
        domain=DOMAIN, title="LifeSpan-TM-2001", unique_id=ADDR,
        data={"address": ADDR}, options={"unit": "mph", "idle_interval": 10},
    )
    entry.add_to_hass(hass)
    started = asyncio.Event()

    async def fake_run(self):
        started.set()

    with patch(
        "custom_components.lifespan_treadmill.bluetooth.async_register_callback",
        return_value=lambda: None,
    ), patch.object(LifeSpanCoordinator, "async_run", fake_run):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    dev = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, ADDR), entry.entry_id)
    assert dev.manufacturer == "LifeSpan Fitness"
    assert (dr.CONNECTION_BLUETOOTH, ADDR) in dev.connections

    ents = {e.unique_id: e for e in er.async_entries_for_device(er.async_get(hass), dev.id, include_disabled_entities=True)}
    assert ents[f"{ADDR}_connected"].entity_category == "diagnostic"
    assert ents[f"{ADDR}_rssi"].disabled_by == er.RegistryEntryDisabler.INTEGRATION
    assert ents[f"{ADDR}_running"].entity_id == "binary_sensor.lifespan_tm_2001_running"
    assert hass.states.get("binary_sensor.lifespan_tm_2001_connectivity").state == "off"
    assert hass.states.get("sensor.lifespan_tm_2001_speed").state == "unavailable"

    # device registry gets DIS info once read
    coord = entry.runtime_data
    coord.device_information = {"model": "SC110", "firmware": "V1.2"}
    coord._update_device_registry()
    dev = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, ADDR), entry.entry_id)
    assert (dev.model_id, dev.sw_version) == ("SC110", "V1.2")

    from custom_components.lifespan_treadmill.diagnostics import (
        async_get_config_entry_diagnostics,
    )
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["connected"] is False and diag["options"]["unit"] == "mph"
    assert await hass.config_entries.async_unload(entry.entry_id)


class LateConsole(FakeConsole):
    """Answers STEPS late, after the request timed out."""

    async def write_gatt_char(self, uuid, data, response):
        op = data[1]
        self.writes.append(op)
        loop = asyncio.get_running_loop()
        delay = 0.08 if op == 0x88 and len(self.writes) > 12 else 0.001
        loop.call_later(delay, self.cb, None, bytearray(self.answers[op]))


async def test_late_reply_is_not_misassigned(hass: HomeAssistant):
    """A late calories-sized reply must never land on steps (or anything else)."""
    answers = dict(ANSWERS)
    coord = LifeSpanCoordinator(hass, MagicMock(), ADDR, "LifeSpan-TM", 10)
    fake = LateConsole(answers)
    seen_steps = []
    coord.async_add_listener(lambda: seen_steps.append(coord.data.steps))
    with patch(
        "custom_components.lifespan_treadmill.coordinator.establish_connection",
        return_value=fake,
    ), patch("custom_components.lifespan_treadmill.coordinator.ACTIVE_GAP", 0), patch(
        "custom_components.lifespan_treadmill.coordinator.RESPONSE_TIMEOUT", 0.04
    ), patch("custom_components.lifespan_treadmill.coordinator.LATE_REPLY_GRACE", 0.06):
        task = asyncio.create_task(coord._connect_and_poll(MagicMock()))
        await asyncio.sleep(1.0)
        fake.is_connected = False
        await asyncio.wait_for(task, 3)
    d = coord.data
    assert (d.speed, d.distance, d.duration_s, d.calories) == (2.2, 1.31, 4005, 235)
    assert all(v in (None, 3950) for v in seen_steps)


async def test_guard_holds_single_drop_in_coordinator(hass: HomeAssistant):
    coord = LifeSpanCoordinator(hass, MagicMock(), ADDR, "LifeSpan-TM", 10)
    coord.data.steps = 3950
    answers = dict(ANSWERS)
    answers[0x88] = bytes.fromhex("a1aa00eb0000")  # 235 — a calories value
    fake = FakeConsole(answers)
    with patch(
        "custom_components.lifespan_treadmill.coordinator.establish_connection",
        return_value=fake,
    ), patch("custom_components.lifespan_treadmill.coordinator.ACTIVE_GAP", 0):
        task = asyncio.create_task(coord._connect_and_poll(MagicMock()))
        # wait for the first steps poll only
        for _ in range(200):
            await asyncio.sleep(0.005)
            if fake.writes.count(0x88) == 1 and coord.data.status is not None:
                break
        assert coord.data.steps == 3950  # first low read held back
        for _ in range(400):
            await asyncio.sleep(0.005)
            if fake.writes.count(0x88) >= 2:
                break
        await asyncio.sleep(0.02)
        fake.is_connected = False
        await asyncio.wait_for(task, 3)
    assert coord.data.steps == 235  # confirmed by second read -> accepted


async def test_session_event_and_last_session_sensors(hass: HomeAssistant):
    from datetime import timedelta

    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from homeassistant.util import dt as dt_util

    from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

    from custom_components.lifespan_treadmill.session import Session

    hass.config.units = US_CUSTOMARY_SYSTEM
    hass.config.components.update({"bluetooth", "bluetooth_adapters"})
    entry = MockConfigEntry(
        domain=DOMAIN, title="LifeSpan-TM-2001", unique_id=ADDR,
        data={"address": ADDR}, options={"unit": "mph", "idle_interval": 10},
    )
    entry.add_to_hass(hass)

    async def fake_run(self):
        return

    with patch(
        "custom_components.lifespan_treadmill.bluetooth.async_register_callback",
        return_value=lambda: None,
    ), patch.object(LifeSpanCoordinator, "async_run", fake_run):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    ev = "event.lifespan_tm_2001_session"
    assert hass.states.get(ev).state == "unknown"
    end = dt_util.utcnow().replace(microsecond=0)
    entry.runtime_data._sessions_completed(
        [Session(started=end - timedelta(minutes=30), ended=end,
                 duration_s=1800, steps=2600, distance=1.25, calories=110)]
    )
    await hass.async_block_till_done()
    st = hass.states.get(ev)
    assert st.attributes["event_type"] == "session_completed"
    assert st.attributes["steps"] == 2600 and st.attributes["distance_unit"] == "mi"
    assert st.attributes["average_speed"] == 2.5
    assert hass.states.get("sensor.lifespan_tm_2001_last_session_steps").state == "2600"
    assert hass.states.get("sensor.lifespan_tm_2001_last_session_distance").state == "1.25"
    assert hass.states.get("sensor.lifespan_tm_2001_last_session_average_speed").state == "2.5"
    assert hass.states.get("sensor.lifespan_tm_2001_last_session_ended").state == end.isoformat()
    # Live data updates must not wipe the last-session values.
    entry.runtime_data.async_set_updated_data(entry.runtime_data.data)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.lifespan_tm_2001_last_session_steps").state == "2600"
    assert await hass.config_entries.async_unload(entry.entry_id)
