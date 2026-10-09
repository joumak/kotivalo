from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from wakeup_light.schedule import active_occurrence, occurrences, phase, upcoming
from wakeup_light.settings import Alarm, RampSettings

TZ = ZoneInfo("Europe/Helsinki")


def alarms(**days) -> list[Alarm]:
    """alarms(mon="07:00") -> only Monday enabled."""
    names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    return [Alarm(enabled=n in days, time=days.get(n, "07:00")) for n in names]


def local(*args) -> datetime:
    return datetime(*args, tzinfo=TZ).astimezone(UTC)


def test_next_alarm_is_in_utc():
    now = local(2026, 10, 11, 12, 0)  # Sunday noon
    occ = upcoming(now, occurrences(now, alarms(mon="07:00"), RampSettings(), TZ))[0]
    assert occ.alarm == datetime(2026, 10, 12, 4, 0, tzinfo=UTC)  # 07:00 EEST
    assert occ.start == occ.alarm - timedelta(minutes=30)
    assert occ.off == occ.alarm + timedelta(minutes=60)
    assert occ.weekday == 0
    assert occ.label(TZ) == "Mon 07:00"


def test_disabled_days_produce_nothing():
    now = local(2026, 10, 11, 12, 0)
    assert occurrences(now, alarms(), RampSettings(), TZ) == []


def test_ramp_that_starts_before_midnight():
    now = local(2026, 10, 12, 23, 50)  # Monday evening
    occs = occurrences(now, alarms(tue="00:10"), RampSettings(), TZ)
    occ = active_occurrence(now, occs)
    assert occ is not None
    assert occ.alarm == local(2026, 10, 13, 0, 10)
    assert phase(occ, now) == "ramp"


def test_ramp_across_autumn_dst_change_lasts_real_minutes():
    # Helsinki falls back at 04:00 EEST -> 03:00 EET on Sunday 2026-10-25.
    now = local(2026, 10, 24, 12, 0)
    ramp = RampSettings(duration_min=60)
    occ = upcoming(now, occurrences(now, alarms(sun="04:15"), ramp, TZ))[0]
    assert occ.alarm == datetime(2026, 10, 25, 2, 15, tzinfo=UTC)  # 04:15 EET
    assert occ.alarm - occ.start == timedelta(minutes=60)


def test_ambiguous_time_uses_first_occurrence():
    now = local(2026, 10, 24, 12, 0)
    occ = upcoming(now, occurrences(now, alarms(sun="03:30"), RampSettings(), TZ))[0]
    assert occ.alarm == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)  # 03:30 EEST


def test_nonexistent_spring_time_moves_an_hour_later():
    # 2027-03-28: clocks jump 03:00 EET -> 04:00 EEST.
    now = local(2027, 3, 27, 12, 0)
    occ = upcoming(now, occurrences(now, alarms(sun="03:30"), RampSettings(), TZ))[0]
    assert occ.alarm == datetime(2027, 3, 28, 1, 30, tzinfo=UTC)  # 04:30 EEST


def test_skipped_alarm_is_not_active():
    now = local(2026, 10, 12, 6, 45)
    occs = occurrences(now, alarms(mon="07:00"), RampSettings(), TZ)
    occ = active_occurrence(now, occs)
    assert occ is not None
    assert active_occurrence(now, occs, skipped=[occ.key]) is None


def test_phases_and_hold_window():
    now = local(2026, 10, 12, 6, 0)
    occ = upcoming(now, occurrences(now, alarms(mon="07:00"), RampSettings(), TZ))[0]
    assert phase(occ, local(2026, 10, 12, 6, 29)) == "pending"
    assert phase(occ, local(2026, 10, 12, 6, 45)) == "ramp"
    assert phase(occ, local(2026, 10, 12, 7, 30)) == "hold"
    assert phase(occ, local(2026, 10, 12, 8, 0)) == "done"


def test_leave_on_means_window_ends_at_alarm():
    now = local(2026, 10, 12, 6, 0)
    ramp = RampSettings(hold_min=0)
    occ = upcoming(now, occurrences(now, alarms(mon="07:00"), ramp, TZ))[0]
    assert occ.off is None
    assert occ.window_end == occ.alarm
    assert active_occurrence(local(2026, 10, 12, 7, 5), [occ]) is None
