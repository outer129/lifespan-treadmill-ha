"""Session tracker + counter guard tests (pure, no HA)."""

import importlib.util
import pathlib
import sys
import types
from datetime import datetime, timedelta, timezone

_pkg_dir = pathlib.Path(__file__).parents[1] / "custom_components/lifespan_treadmill"
# Load protocol + session as a tiny stand-alone package (no HA imports needed).
pkg = types.ModuleType("lspkg")
pkg.__path__ = [str(_pkg_dir)]
sys.modules["lspkg"] = pkg
for name in ("protocol", "session"):
    spec = importlib.util.spec_from_file_location(f"lspkg.{name}", _pkg_dir / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"lspkg.{name}"] = mod
    spec.loader.exec_module(mod)
proto = sys.modules["lspkg.protocol"]
sess = sys.modules["lspkg.session"]

T0 = datetime(2026, 11, 25, 14, 0, tzinfo=timezone.utc)
RUN, PAUSE, SUMMARY, STANDBY = 3, 5, 4, 1


def R(status, dur=None, steps=None, dist=None, cal=None):
    return proto.Readout(status=status, duration_s=dur, steps=steps, distance=dist, calories=cal)


def feed(tracker, seq, start=T0, step=timedelta(seconds=1)):
    done, t = [], start
    for r, is_status in seq:
        done += tracker.update(r, is_status, t)
        t += step
    return done, t


# ---------------------------------------------------------------- guard
def test_guard_accepts_increase_and_rejects_single_drop():
    g = proto.CounterGuard()
    assert g.check("steps", None, 5)
    assert g.check("steps", 100, 120)
    assert not g.check("steps", 120, 3)     # glitch
    assert g.check("steps", 120, 125)       # normal again, pending cleared
    assert not g.check("steps", 125, 3)     # glitch again...
    assert g.check("steps", 125, 0)         # ...confirmed by a second, lower read


def test_guard_fields_are_independent():
    g = proto.CounterGuard()
    assert not g.check("steps", 100, 0)
    assert not g.check("calories", 50, 0)
    assert g.check("steps", 100, 0)


# ---------------------------------------------------------------- tracker
def test_normal_session():
    tr = sess.SessionTracker()
    done, _ = feed(tr, [
        (R(RUN, 0, 0, 0, 0), True),
        (R(RUN, 1, 0, 0, 0), True),          # running confirmed -> session open
        (R(RUN, 600, 900, 0.5, 40), False),
        (R(RUN, 1200, 1800, 1.01, 80), False),
        (R(SUMMARY, 1200, 1800, 1.01, 80), True),
        (R(SUMMARY, 1200, 1800, 1.01, 80), True),  # summary confirmed -> done
    ])
    assert len(done) == 1
    s = done[0]
    assert (s.duration_s, s.steps, s.distance, s.calories) == (1200, 1800, 1.01, 80)
    assert s.average_speed == round(1.01 / (1200 / 3600), 2)
    assert tr.current is None


def test_single_bogus_status_does_not_end_session():
    tr = sess.SessionTracker()
    done, _ = feed(tr, [
        (R(RUN, 10, 10), True), (R(RUN, 11, 12), True),
        (R(STANDBY, 12, 14), True),            # one glitchy read
        (R(RUN, 13, 16), True),
        (R(RUN, 100, 150), False),
    ])
    assert done == [] and tr.current.steps == 150


def test_pause_keeps_session_open():
    tr = sess.SessionTracker()
    done, _ = feed(tr, [
        (R(RUN, 10, 10), True), (R(RUN, 11, 12), True),
        (R(PAUSE, 300, 400), True), (R(PAUSE, 300, 400), True),
        (R(RUN, 301, 401), True), (R(RUN, 302, 402), True),
        (R(RUN, 600, 800), False),
    ])
    assert done == [] and tr.current.duration_s == 600


def test_standby_zeros_do_not_clobber_totals():
    tr = sess.SessionTracker()
    done, _ = feed(tr, [
        (R(RUN, 10, 10), True), (R(RUN, 900, 1500, 0.7, 60), True),
        (R(STANDBY, 0, 0, 0, 0), True), (R(STANDBY, 0, 0, 0, 0), True),
    ])
    assert len(done) == 1 and done[0].steps == 1500 and done[0].duration_s == 900


def test_short_noise_session_is_dropped():
    tr = sess.SessionTracker()
    done, _ = feed(tr, [
        (R(RUN, 1, 0), True), (R(RUN, 2, 0), True),
        (R(STANDBY, 3, 0), True), (R(STANDBY, 3, 0), True),
    ])
    assert done == []


def test_start_time_backdated_when_joining_mid_session():
    tr = sess.SessionTracker()
    feed(tr, [(R(RUN, 600, 700), True), (R(RUN, 600, 700), True)])
    assert tr.current.started == T0 + timedelta(seconds=1) - timedelta(seconds=600)


def test_reconnect_same_session_continues():
    tr = sess.SessionTracker()
    _, t = feed(tr, [(R(RUN, 10, 10), True), (R(RUN, 300, 400), True)])
    tr.disconnected(t)
    done, _ = feed(tr, [(R(RUN, 360, 470), True), (R(RUN, 361, 472), True)], start=t + timedelta(seconds=60))
    assert done == [] and tr.current.steps == 472


def test_reconnect_into_new_session_closes_old_one():
    tr = sess.SessionTracker()
    _, t = feed(tr, [(R(RUN, 10, 10), True), (R(RUN, 1800, 2500), True)])
    tr.disconnected(t)
    done, _ = feed(tr, [(R(RUN, 60, 80), True), (R(RUN, 61, 82), True)], start=t + timedelta(hours=2))
    assert len(done) == 1 and done[0].steps == 2500
    assert tr.current is not None and tr.current.steps == 82


def test_disconnect_timeout_closes_session():
    tr = sess.SessionTracker()
    _, t = feed(tr, [(R(RUN, 10, 10), True), (R(RUN, 900, 1200), True)])
    tr.disconnected(t)
    assert tr.check_timeout(t + timedelta(minutes=14)) == []
    done = tr.check_timeout(t + timedelta(minutes=15))
    assert len(done) == 1 and done[0].steps == 1200 and tr.current is None


def test_reconnect_resets_status_confirmation():
    tr = sess.SessionTracker()
    _, t = feed(tr, [(R(RUN, 10, 10), True), (R(RUN, 900, 1200), True)])
    tr.disconnected(t)
    # A single standby read right after reconnect is not enough to end it.
    done, _ = feed(tr, [(R(STANDBY, 0, 0), True)], start=t + timedelta(seconds=30))
    assert done == [] and tr.current is not None
