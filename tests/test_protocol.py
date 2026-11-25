"""Protocol tests — frames taken from treadspan captures and trot's SC110 tests."""

import importlib.util
import pathlib
import sys

import pytest

_p = pathlib.Path(__file__).parents[1] / "custom_components/lifespan_treadmill/protocol.py"
_spec = importlib.util.spec_from_file_location("lsprotocol", _p)
proto = importlib.util.module_from_spec(_spec)
sys.modules["lsprotocol"] = proto
_spec.loader.exec_module(proto)

O = proto.Opcode


def hx(s):
    return bytes.fromhex(s)


def test_request():
    assert proto.build_request(O.STEPS) == hx("a1 88 00 00 00 00")


@pytest.mark.parametrize(
    "op,frame,attr,val",
    [
        (O.STEPS, "a1 aa 0f 6e 00 00", "steps", 3950),
        (O.CALORIES, "a1 aa 00 0a 00 00", "calories", 10),
        (O.DISTANCE, "a1 aa 01 1f 00 00", "distance", 1.31),  # console showed 1.3 mi
        (O.SPEED, "a1 aa 02 00 00 00", "speed", 2.0),
        (O.SPEED, "a1 aa 00 3c 00 00", "speed", 0.6),
        (O.DURATION, "a1 aa 01 06 2d 00", "duration_s", 4005),  # 1:06:45
        (O.STATUS, "a1 aa 03 00 00 00", "status", 3),
    ],
)
def test_decode(op, frame, attr, val):
    r = proto.Readout()
    proto.decode_into(r, op, hx(frame))
    assert getattr(r, attr) == val


@pytest.mark.parametrize(
    "op,frame",
    [
        (O.STEPS, "a1 ff 00 00 00 00"),
        (O.STEPS, "a1 aa 00 06"),
        (O.STEPS, "a2 aa 00 06 00 00"),
        (O.DURATION, "a1 aa 00 3c 00 00"),
        (O.STATUS, "a1 aa 03 01 00 00"),
    ],
)
def test_bad_frames_leave_state(op, frame):
    r = proto.Readout(steps=5, status=1)
    with pytest.raises(proto.ProtocolError):
        proto.decode_into(r, op, hx(frame))
    assert r.steps == 5 and r.status == 1


def test_status_helpers():
    r = proto.Readout(status=5)
    assert r.status_name == "paused" and r.session_active and not r.is_running
    assert proto.Readout(status=0x7F).status_name == "unknown"
