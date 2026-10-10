"""Pure alarm scheduling: which alarm occurrences exist and which one is active.

Alarms are local wall-clock times; every computed instant is UTC, so a ramp that
crosses a DST change still lasts its full real duration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from kotivalo.settings import WEEKDAYS, Alarm, RampSettings

LOOKBACK_DAYS = 1  # an alarm's window (ramp + hold) can start the previous evening
LOOKAHEAD_DAYS = 8


@dataclass(frozen=True)
class Occurrence:
    alarm: datetime  # UTC instant of full brightness
    start: datetime  # UTC ramp start
    off: datetime | None  # UTC auto-off, None = leave on
    weekday: int  # 0 = Monday, of the alarm's local date
    local_time: str  # "HH:MM" as configured

    @property
    def key(self) -> str:
        return self.alarm.isoformat()

    @property
    def window_end(self) -> datetime:
        """Until when the service is responsible for this alarm."""
        return self.off or self.alarm

    def label(self, tz: ZoneInfo) -> str:
        local = self.alarm.astimezone(tz)
        return f"{WEEKDAYS[self.weekday]} {local:%H:%M}"


def alarm_instant(day: date, hhmm: str, tz: ZoneInfo) -> datetime:
    """UTC instant of a local wall-clock time.

    Ambiguous times (autumn) use the first occurrence. Nonexistent times (spring
    gap) resolve with the pre-gap offset, i.e. one hour later on the wall clock.
    """
    local = datetime.combine(day, time.fromisoformat(hhmm), tzinfo=tz)
    return local.astimezone(UTC)


def occurrences(now: datetime, alarms: list[Alarm], ramp: RampSettings, tz: ZoneInfo):
    today = now.astimezone(tz).date()
    result = []
    for offset in range(-LOOKBACK_DAYS, LOOKAHEAD_DAYS):
        day = today + timedelta(days=offset)
        alarm = alarms[day.weekday()]
        if not alarm.enabled:
            continue
        at = alarm_instant(day, alarm.time, tz)
        result.append(
            Occurrence(
                alarm=at,
                start=at - timedelta(minutes=ramp.duration_min),
                off=at + timedelta(minutes=ramp.hold_min) if ramp.hold_min else None,
                weekday=day.weekday(),
                local_time=alarm.time,
            )
        )
    return sorted(result, key=lambda o: o.alarm)


def active_occurrence(now: datetime, occs: list[Occurrence], skipped=()) -> Occurrence | None:
    """The alarm whose ramp or hold window contains now (the latest if windows overlap)."""
    active = [o for o in occs if o.start <= now < o.window_end and o.key not in skipped]
    return active[-1] if active else None


def upcoming(now: datetime, occs: list[Occurrence]) -> list[Occurrence]:
    """Alarms whose ramp has not started yet, soonest first."""
    return [o for o in occs if o.start > now]


def phase(occ: Occurrence, now: datetime) -> str:
    if now < occ.start:
        return "pending"
    if now < occ.alarm:
        return "ramp"
    if now < occ.window_end:
        return "hold"
    return "done"
