"""LifeSpan console (SC110 / Omni) BLE protocol — pure, dependency-free.

Protocol (reverse engineered by blak3r/treadspan, confirmed on SC110 by
marcuspuchalla/trot):

* Service 0xFFF0. Subscribe to notifications on 0xFFF1, write requests to 0xFFF2.
* Request:  ``A1 <opcode> 00 00 00 00``
* Response: ``A1 AA <b2> <b3> <b4> <b5>`` (``A1 FF ...`` = unknown opcode).
* The response does NOT echo the opcode, so requests must be strictly serialised.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
WRITE_CHAR_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"

REQ_PREFIX = 0xA1
RESP_OK = 0xAA
RESP_ERR = 0xFF


class Opcode(IntEnum):
    SPEED = 0x82
    DISTANCE = 0x85
    CALORIES = 0x87
    STEPS = 0x88
    DURATION = 0x89
    STATUS = 0x91


class Status(IntEnum):
    STANDBY = 1
    RUNNING = 3
    SUMMARY = 4
    PAUSED = 5


STATUS_NAMES = {
    Status.STANDBY: "standby",
    Status.RUNNING: "running",
    Status.SUMMARY: "summary",
    Status.PAUSED: "paused",
}

# Polled while a session is active: speed interleaved so it feels live.
ACTIVE_ROTATION: tuple[Opcode, ...] = (
    Opcode.STATUS,
    Opcode.SPEED,
    Opcode.STEPS,
    Opcode.SPEED,
    Opcode.DISTANCE,
    Opcode.SPEED,
    Opcode.DURATION,
    Opcode.SPEED,
    Opcode.CALORIES,
)
# Polled once per idle cycle.
IDLE_ROTATION: tuple[Opcode, ...] = (
    Opcode.STATUS,
    Opcode.STEPS,
    Opcode.DISTANCE,
    Opcode.DURATION,
    Opcode.CALORIES,
    Opcode.SPEED,
)


class ProtocolError(ValueError):
    """Frame could not be decoded."""


def build_request(opcode: int) -> bytes:
    return bytes((REQ_PREFIX, opcode, 0, 0, 0, 0))


def _validate(frame: bytes) -> None:
    if len(frame) != 6:
        raise ProtocolError(f"expected 6 bytes, got {len(frame)}")
    if frame[0] != REQ_PREFIX:
        raise ProtocolError(f"bad prefix 0x{frame[0]:02x}")
    if frame[1] == RESP_ERR:
        raise ProtocolError("console reported unknown opcode")
    if frame[1] != RESP_OK:
        raise ProtocolError(f"unexpected flag 0x{frame[1]:02x}")


def _u16(frame: bytes) -> int:
    return (frame[2] << 8) | frame[3]


def _whole_hundredths(frame: bytes) -> float:
    """byte2 = whole units, byte3 = hundredths (in the console's display unit)."""
    if frame[3] > 99:
        raise ProtocolError(f"hundredths byte out of range: {frame[3]}")
    return round(frame[2] + frame[3] / 100, 2)


@dataclass
class Readout:
    """Latest known values, accumulated across polls."""

    status: int | None = None
    speed: float | None = None  # display unit (mph or km/h)
    distance: float | None = None  # display unit (mi or km)
    steps: int | None = None
    calories: int | None = None
    duration_s: int | None = None
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def status_name(self) -> str | None:
        if self.status is None:
            return None
        return STATUS_NAMES.get(self.status, "unknown")  # type: ignore[call-overload]

    @property
    def is_running(self) -> bool:
        return self.status == Status.RUNNING

    @property
    def session_active(self) -> bool:
        return self.status in (Status.RUNNING, Status.PAUSED)


def decode_into(readout: Readout, opcode: int, frame: bytes) -> None:
    """Decode ``frame`` (the reply to ``opcode``) into ``readout``.

    Raises ProtocolError and leaves ``readout`` untouched on a bad frame.
    """
    _validate(frame)
    if opcode == Opcode.STEPS:
        readout.steps = _u16(frame)
    elif opcode == Opcode.CALORIES:
        readout.calories = _u16(frame)
    elif opcode == Opcode.SPEED:
        readout.speed = _whole_hundredths(frame)
    elif opcode == Opcode.DISTANCE:
        readout.distance = _whole_hundredths(frame)
    elif opcode == Opcode.DURATION:
        h, m, s = frame[2], frame[3], frame[4]
        if m >= 60 or s >= 60:
            raise ProtocolError(f"bad duration {h}:{m}:{s}")
        readout.duration_s = h * 3600 + m * 60 + s
    elif opcode == Opcode.STATUS:
        if frame[3] or frame[4]:
            # Treadspan observed these occasionally — not a real status reply.
            raise ProtocolError("implausible status frame")
        readout.status = frame[2]
    else:
        return
    readout.raw[Opcode(opcode).name.lower()] = frame.hex(" ")


# Per-session cumulative counters on the console, keyed by the opcode that reads them.
COUNTER_FIELDS: dict[int, str] = {
    Opcode.STEPS: "steps",
    Opcode.DISTANCE: "distance",
    Opcode.CALORIES: "calories",
    Opcode.DURATION: "duration_s",
}


class CounterGuard:
    """Reject single-sample drops in the console's cumulative counters.

    The console's replies don't name the opcode they answer, so one late reply can be
    decoded as the wrong field. To HA's statistics a drop in a total_increasing sensor
    means a reset, so one bad sample would count the whole session twice. A drop is
    accepted on the second read in a row that is also below the old value. A real
    reset stays below it; a glitch goes back up. The second read doesn't have to equal
    the first: after a real reset the counter is already climbing again.
    """

    def __init__(self) -> None:
        self._pending: set[str] = set()

    def check(self, field_name: str, old: float | None, new: float) -> bool:
        """Return True if ``new`` should replace ``old``."""
        if old is None or new >= old:
            self._pending.discard(field_name)
            return True
        if field_name in self._pending:
            self._pending.discard(field_name)
            return True
        self._pending.add(field_name)
        return False

    def reset(self) -> None:
        self._pending.clear()
