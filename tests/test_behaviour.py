"""The owner model: every rule, with explicit times."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from kotivalo.behaviour import Behaviour, SwitchOff, SwitchOn, night_now
from kotivalo.settings import MotionRule, NightWindow, Profile, Settings

LAMP = "d0:cf:5e:ff:fe:1f:a3:9e"
OTHER = "50:32:5f:ff:fe:6e:e5:2c"
SENSOR = "11:22:33:44:55:66:77:88"
T0 = datetime(2026, 10, 12, 18, 0, tzinfo=UTC)
TZ = ZoneInfo("Europe/Helsinki")


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def make(**rule) -> Behaviour:
    settings = Settings()
    settings.motion = [
        MotionRule(
            sensor=SENSOR,
            lights=[LAMP],
            dark_lux=30,
            off_after_min=5,
            day=Profile(254, 2700),
            night=Profile(13, 2200),
            **rule,
        )
    ]
    return Behaviour(settings)


def test_motion_in_the_dark_switches_on_with_the_day_profile():
    b = make()
    assert b.motion(SENSOR, True, at(0), night=False) == [SwitchOn(LAMP, 254, 2700)]
    assert b.lamp(LAMP).owner == "motion"


def test_motion_at_night_gives_the_dim_warm_night_light():
    b = make()
    assert b.motion(SENSOR, True, at(0), night=True) == [SwitchOn(LAMP, 13, 2200)]
    assert b.lamp(LAMP).profile == "night"


def test_bright_room_does_not_switch_on_but_night_always_does():
    b = make()
    b.lux(SENSOR, 200, at(0))
    assert b.motion(SENSOR, True, at(1), night=False) == []
    assert b.lamp(LAMP).owner == "off"
    assert b.motion(SENSOR, True, at(2), night=True) == [SwitchOn(LAMP, 13, 2200)]


def test_lux_measured_while_the_lamp_shines_is_not_trusted():
    b = make()
    b.motion(SENSOR, True, at(0), night=False)  # on by motion
    b.lux(SENSOR, 300, at(1))  # the lamp's own light
    b.motion(SENSOR, False, at(2), night=False)
    assert b.tick(at(7)) == [SwitchOff(LAMP)]
    b.lux(SENSOR, 300, at(7.5))  # 30 s after switching off: still not settled
    assert b.motion(SENSOR, True, at(7.6), night=False) == [SwitchOn(LAMP, 254, 2700)]
    assert b.sensor(SENSOR).lux is None


def test_the_lamp_goes_off_when_the_room_has_been_empty_long_enough():
    b = make()
    b.motion(SENSOR, True, at(0), night=False)
    b.motion(SENSOR, False, at(1), night=False)
    assert b.next_deadline() == at(6)
    assert b.tick(at(5.9)) == []
    b.motion(SENSOR, True, at(5.95), night=False)  # back in the room: timer cancelled
    assert b.lamp(LAMP).off_at is None
    assert b.next_deadline() == at(15.95)  # only the stuck-sensor check remains
    b.motion(SENSOR, False, at(10), night=False)
    assert b.tick(at(15)) == [SwitchOff(LAMP)]
    assert b.lamp(LAMP).owner == "off"


def test_manual_wins_motion_never_switches_it_off():
    b = make()
    b.motion(SENSOR, True, at(0), night=False)
    b.manual(LAMP, True, at(1))  # dimmed from the UI: now manual
    b.motion(SENSOR, False, at(2), night=False)
    assert b.tick(at(60)) == []
    assert b.lamp(LAMP).owner == "manual"


def test_switch_off_and_walk_out_without_it_coming_back():
    b = make()
    b.motion(SENSOR, True, at(0), night=False)
    b.manual(LAMP, False, at(1))  # off while still in the room
    assert b.motion(SENSOR, True, at(1.5), night=False) == []  # still in the room
    b.motion(SENSOR, False, at(2), night=False)  # walked out
    assert b.motion(SENSOR, True, at(4), night=False) == []  # back within 5 min: still ignored
    b.motion(SENSOR, False, at(5), night=False)
    assert b.motion(SENSOR, True, at(11), night=False) == [SwitchOn(LAMP, 254, 2700)]


def test_manual_off_in_an_empty_room_ignores_motion_for_a_while():
    b = make()
    b.manual(LAMP, False, at(0))
    assert b.motion(SENSOR, True, at(3), night=False) == []
    b.motion(SENSOR, False, at(3.5), night=False)
    assert b.motion(SENSOR, True, at(9), night=False) == [SwitchOn(LAMP, 254, 2700)]


def test_the_profile_is_fixed_for_the_motion_period():
    b = make()
    b.motion(SENSOR, True, at(0), night=False)
    assert b.motion(SENSOR, True, at(1), night=True) == []  # night began: no jump to 5 %
    assert b.lamp(LAMP).profile == "day"


def test_a_wall_switch_is_followed():
    b = make()
    b.lamp_state(LAMP, True, at(0))  # switched on at the wall
    assert b.lamp(LAMP).owner == "manual"
    b.lamp_state(LAMP, False, at(1))
    assert b.lamp(LAMP).owner == "off"
    b.motion(SENSOR, True, at(2), night=False)
    b.lamp_state(LAMP, True, at(2.2))  # our own switch-on, reported back
    assert b.lamp(LAMP).owner == "motion"


def test_a_sunrise_owns_the_lamp_and_motion_is_ignored():
    b = make()
    b.sunrise_started(LAMP)
    assert b.motion(SENSOR, True, at(0), night=True) == []
    assert b.lamp(LAMP).owner == "sunrise"


def test_after_the_sunrise_an_occupied_room_keeps_the_light():
    b = make()
    b.sunrise_started(LAMP)
    b.motion(SENSOR, True, at(0), night=False)
    b.motion(SENSOR, False, at(1), night=False)
    assert b.keep_on_after_sunrise(LAMP, at(3)) is True
    assert b.lamp(LAMP).owner == "motion" and b.lamp(LAMP).off_at == at(6)
    assert b.tick(at(6)) == [SwitchOff(LAMP)]


def test_after_the_sunrise_an_empty_room_switches_off():
    b = make()
    b.sunrise_started(LAMP)
    assert b.keep_on_after_sunrise(LAMP, at(30)) is False
    b.sunrise_ended(LAMP, lamp_on=False, now=at(30))
    assert b.lamp(LAMP).owner == "off"


def test_a_lamp_that_was_manual_before_the_alarm_stays_manual():
    b = make()
    b.manual(LAMP, True, at(0))
    b.sunrise_started(LAMP)
    assert b.keep_on_after_sunrise(LAMP, at(60)) is True
    assert b.lamp(LAMP).owner == "manual"


def test_a_sunrise_that_leaves_the_lamp_on_hands_it_to_manual():
    b = make()
    b.sunrise_started(LAMP)
    b.sunrise_ended(LAMP, lamp_on=True, now=at(30))
    assert b.lamp(LAMP).owner == "manual"


def test_a_silent_sensor_is_treated_as_empty():
    b = make()
    b.motion(SENSOR, True, at(0), night=False)
    assert b.next_deadline() == at(10)  # 600 s without a report
    assert b.tick(at(10)) == []  # now "empty": the off timer starts
    assert b.lamp(LAMP).off_at == at(15)
    assert b.tick(at(15)) == [SwitchOff(LAMP)]


def test_disabled_rules_and_lamps_without_rules_do_nothing():
    b = make(enabled=False)
    assert b.motion(SENSOR, True, at(0), night=False) == []
    b2 = make()
    b2.manual(OTHER, False, at(0))  # a lamp without a rule
    assert b2.lamp(OTHER).suppressed_until is None


def test_owners_survive_a_restart():
    b = make()
    b.motion(SENSOR, True, at(0), night=True)
    b.motion(SENSOR, False, at(1), night=True)
    restored = make()
    restored.load(b.to_dict())
    assert restored.lamp(LAMP) == b.lamp(LAMP)
    assert restored.tick(at(30)) == [SwitchOff(LAMP)]  # overdue while the service was down


@pytest.mark.parametrize(
    ("local", "ramp_start", "expected"),
    [
        ("2026-10-12 22:59", None, False),
        ("2026-10-12 23:00", None, True),
        ("2026-10-13 03:00", None, True),
        ("2026-10-13 06:59", None, True),
        ("2026-10-13 07:00", None, False),
        ("2026-10-13 06:10", "2026-10-13 06:00", False),  # the sunrise has started
        ("2026-10-13 05:50", "2026-10-13 06:00", True),
        ("2026-10-25 03:30", None, True),  # the autumn DST night (03:00-04:00 twice)
    ],
)
def test_night_window(local, ramp_start, expected):
    def parse(text):
        return datetime.fromisoformat(text).replace(tzinfo=TZ).astimezone(UTC)

    start = parse(ramp_start) if ramp_start else None
    assert night_now(parse(local), TZ, NightWindow("23:00", "07:00"), start) is expected
