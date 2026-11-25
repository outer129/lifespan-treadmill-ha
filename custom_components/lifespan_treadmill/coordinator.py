"""Connection manager / coordinator for a LifeSpan console."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
)

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .protocol import (
    ACTIVE_ROTATION,
    IDLE_ROTATION,
    NOTIFY_CHAR_UUID,
    WRITE_CHAR_UUID,
    Opcode,
    ProtocolError,
    Readout,
    build_request,
    decode_into,
)

_LOGGER = logging.getLogger(__name__)

RESPONSE_TIMEOUT = 2.0
ACTIVE_GAP = 0.25  # seconds between requests while a session is active
MAX_MISSED = 6  # consecutive unanswered requests before forcing a reconnect
RECONNECT_BACKOFF = (5, 10, 30, 60)


class LifeSpanCoordinator(DataUpdateCoordinator[Readout]):
    """Holds a BLE connection to the console and polls it."""

    def __init__(
        self, hass: HomeAssistant, address: str, name: str, idle_interval: int
    ) -> None:
        super().__init__(hass, _LOGGER, name=f"{DOMAIN} {address}")
        self.address = address
        self.device_name = name
        self.idle_interval = idle_interval
        self.data = Readout()
        self.last_update_success = False  # unavailable until first connect
        self.connected = False
        self._client: BleakClient | None = None
        self._response: asyncio.Future[bytes] | None = None
        self._seen = asyncio.Event()
        self._write_with_response = True

    # ------------------------------------------------------------------ setup
    @callback
    def async_on_advertisement(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Wake the run loop when the console advertises."""
        self._seen.set()

    async def async_run(self) -> None:
        """Run forever: connect, poll, reconnect."""
        attempt = 0
        while True:
            device = bluetooth.async_ble_device_from_address(
                self.hass, self.address, connectable=True
            )
            if device is None:
                self._mark_disconnected("not in range of any connectable adapter")
                self._seen.clear()
                try:
                    await asyncio.wait_for(self._seen.wait(), timeout=60)
                except TimeoutError:
                    pass
                continue
            try:
                await self._connect_and_poll(device)
                attempt = 0
            except (BleakError, TimeoutError, OSError) as err:
                _LOGGER.debug("%s: connection error: %s", self.address, err)
            except Exception:  # keep the loop alive no matter what
                _LOGGER.exception("%s: unexpected error", self.address)
            finally:
                await self._disconnect()
            delay = RECONNECT_BACKOFF[min(attempt, len(RECONNECT_BACKOFF) - 1)]
            attempt += 1
            self._mark_disconnected("disconnected")
            await asyncio.sleep(delay)

    async def async_shutdown(self) -> None:
        await self._disconnect()
        await super().async_shutdown()

    # ------------------------------------------------------------ connection
    async def _connect_and_poll(self, device: BLEDevice) -> None:
        _LOGGER.debug("%s: connecting", self.address)
        client = await establish_connection(
            BleakClientWithServiceCache,
            device,
            self.device_name,
            disconnected_callback=self._on_disconnect,
            max_attempts=3,
        )
        self._client = client
        write_char = client.services.get_characteristic(WRITE_CHAR_UUID)
        notify_char = client.services.get_characteristic(NOTIFY_CHAR_UUID)
        if write_char is None or notify_char is None:
            raise BleakError("console is missing FFF1/FFF2 characteristics")
        self._write_with_response = "write" in write_char.properties
        await client.start_notify(notify_char, self._on_notify)
        self.connected = True
        _LOGGER.info("Connected to LifeSpan console %s", self.address)

        missed = 0
        while client.is_connected:
            rotation = ACTIVE_ROTATION if self.data.session_active else IDLE_ROTATION
            for opcode in rotation:
                if not client.is_connected:
                    return
                frame = await self._request(client, opcode)
                if frame is None:
                    missed += 1
                    if missed >= MAX_MISSED:
                        raise TimeoutError("console stopped answering")
                    continue
                missed = 0
                new = replace(self.data, raw=dict(self.data.raw))
                try:
                    decode_into(new, opcode, frame)
                except ProtocolError as err:
                    _LOGGER.debug(
                        "%s: bad reply to 0x%02x (%s): %s",
                        self.address, opcode, frame.hex(" "), err,
                    )
                    continue
                self.async_set_updated_data(new)
                if self.data.session_active:
                    await asyncio.sleep(ACTIVE_GAP)
            if not self.data.session_active:
                await asyncio.sleep(self.idle_interval)

    async def _request(self, client: BleakClient, opcode: Opcode) -> bytes | None:
        """Send one request and wait for its (un-tagged) reply."""
        loop = asyncio.get_running_loop()
        self._response = loop.create_future()
        try:
            await client.write_gatt_char(
                WRITE_CHAR_UUID,
                build_request(opcode),
                response=self._write_with_response,
            )
            return await asyncio.wait_for(self._response, RESPONSE_TIMEOUT)
        except TimeoutError:
            _LOGGER.debug("%s: no reply to 0x%02x", self.address, opcode)
            return None
        finally:
            self._response = None

    def _on_notify(self, _char, data: bytearray) -> None:
        fut = self._response
        if fut is not None and not fut.done():
            fut.set_result(bytes(data))
        # else: stale/unsolicited frame — drop it so it can't be mis-assigned.

    def _on_disconnect(self, _client: BleakClient) -> None:
        _LOGGER.debug("%s: disconnected", self.address)
        self.connected = False
        fut = self._response
        if fut is not None and not fut.done():
            fut.set_exception(BleakError("disconnected"))

    async def _disconnect(self) -> None:
        client, self._client = self._client, None
        self.connected = False
        if client is not None:
            try:
                await client.disconnect()
            except BleakError:
                pass

    @callback
    def _mark_disconnected(self, reason: str) -> None:
        if self.last_update_success:
            _LOGGER.debug("%s: unavailable (%s)", self.address, reason)
            self.async_set_update_error(BleakError(reason))
