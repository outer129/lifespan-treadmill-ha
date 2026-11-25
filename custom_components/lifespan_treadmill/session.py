"""Session tracking for a LifeSpan console — pure Python, no Home Assistant imports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .protocol import Readout, Status

# A status must be read this many times in a row before we act on it (treadspan
# found single bogus status replies in practice).
STATUS_CONFIRMATIONS = 2
# Sessions shorter than this with no steps are console noise (pressing start/stop).
MIN_DURATION_S = 30
# If the link has been down this long, a still-open session is considered finished.
DISCONNECT_TIMEOUT = timedelta(minutes=15)
# Session time dropping by more than this while running means a new session began
# without us ever seeing the previous one end.
NEW_SESSION_DURATION_DROP_S = 5


@dataclass
class Session:
    started: datetime
    ended: datetime
    duration_s: int = 0
    steps: int = 0
    distance: float = 0.0
    calories: int = 0

    @property
    def average_speed(self) -> float | None:
        """Average speed in the console's display unit per hour."""
        if self.duration_s <= 0:
            return None
        return round(self.distance / (self.duration_s / 3600), 2)

    @property
    def meaningful(self) -> bool:
        return self.steps > 0 or self.duration_s >= MIN_DURATION_S

    def absorb(self, r: Readout) -> None:
        """Counters only grow within a session, so keep the max seen."""
        self.duration_s = max(self.duration_s, r.duration_s or 0)
        self.steps = max(self.steps, r.steps or 0)
        self.distance = max(self.distance, r.distance or 0.0)
        self.calories = max(self.calories, r.calories or 0)


class SessionTracker:
    """Turns the stream of polled readouts into completed sessions."""

    def __init__(self) -> None:
        self.current: Session | None = None
        self._last_status: int | None = None
        self._status_count = 0
        self._confirmed_status: int | None = None
        self._disconnected_at: datetime | None = None

    def update(self, r: Readout, status_frame: bool, now: datetime) -> list[Session]:
        """Feed one decoded readout. Returns any sessions that just completed."""
        done: list[Session] = []
        self._disconnected_at = None
        if status_frame and r.status is not None:
            if r.status == self._last_status:
                self._status_count += 1
            else:
                self._last_status, self._status_count = r.status, 1
            if self._status_count >= STATUS_CONFIRMATIONS:
                self._confirmed_status = r.status

        status = self._confirmed_status
        cur = self.current

        # A new session started while we weren't looking (or across a reconnect).
        if (
            cur is not None
            and status in (Status.RUNNING, Status.PAUSED)
            and r.duration_s is not None
            and r.duration_s < cur.duration_s - NEW_SESSION_DURATION_DROP_S
        ):
            done += self._finish()
            cur = None

        if cur is None:
            if status == Status.RUNNING:
                start = now - timedelta(seconds=r.duration_s or 0)
                self.current = cur = Session(started=start, ended=now)
                cur.absorb(r)
            return done

        if status in (Status.RUNNING, Status.PAUSED):
            cur.absorb(r)
            if r.status in (Status.RUNNING, Status.PAUSED):
                cur.ended = now  # not while an unconfirmed summary is showing
        elif status in (Status.SUMMARY, Status.STANDBY):
            # Summary still shows the totals, so take them; standby may already
            # show zeros, which absorb()'s max ignores.
            cur.absorb(r)
            done += self._finish()
        return done

    @property
    def confirmed_status(self) -> int | None:
        return self._confirmed_status

    @property
    def idle(self) -> bool:
        """Console confirmed on standby or the summary screen."""
        return self._confirmed_status in (Status.STANDBY, Status.SUMMARY)

    def disconnected(self, now: datetime) -> None:
        if self._disconnected_at is None:
            self._disconnected_at = now
        # Status must be confirmed again after a reconnect.
        self._last_status, self._status_count, self._confirmed_status = None, 0, None

    def check_timeout(self, now: datetime) -> list[Session]:
        if (
            self.current is not None
            and self._disconnected_at is not None
            and now - self._disconnected_at >= DISCONNECT_TIMEOUT
        ):
            return self._finish()
        return []

    def _finish(self) -> list[Session]:
        cur, self.current = self.current, None
        return [cur] if cur is not None and cur.meaningful else []
