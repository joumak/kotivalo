"""Daylight warmth: the sun's times and the curve between them."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from kotivalo.daylight import coolness, day_points, daylight_mireds, sun_times
from kotivalo.settings import DaylightSettings, SettingsError

TZ = ZoneInfo("Europe/Helsinki")
HELSINKI = (60.17, 24.94)


def local(d: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m, tzinfo=TZ)


@pytest.mark.parametrize(
    ("day", "sunrise", "sunset"),
    [
        (date(2026, 6, 21), "03:54", "22:50"),  # published times for Helsinki
        (date(2026, 12, 21), "09:24", "15:13"),
    ],
)
def test_sun_times_in_helsinki(day, sunrise, sunset):
    sun = sun_times(day, *HELSINKI)
    assert abs(sun.sunrise - local(day, sunrise)) <= timedelta(minutes=2)
    assert abs(sun.sunset - local(day, sunset)) <= timedelta(minutes=2)


def test_polar_day_and_night():
    tromso = (69.65, 18.96)
    assert sun_times(date(2026, 6, 21), *tromso).polar == "day"
    assert sun_times(date(2026, 12, 21), *tromso).polar == "night"
    day = DaylightSettings()
    noon = datetime(2026, 6, 21, 10, tzinfo=UTC)
    assert daylight_mireds(noon, TZ, *tromso, day) == 250  # 4000 K all day
    assert daylight_mireds(noon.replace(month=12), TZ, *tromso, day) == 370  # 2700 K


def test_warm_at_sunrise_cool_by_day_warm_again_at_sunset():
    settings = DaylightSettings()  # cools over 2 h from sunrise, warms over 2 h to sunset
    day = date(2026, 10, 23)
    sun = sun_times(day, *HELSINKI)
    at = lambda moment: daylight_mireds(moment, TZ, *HELSINKI, settings)  # noqa: E731
    assert at(sun.sunrise - timedelta(hours=1)) == 370
    assert at(sun.sunrise) == 370
    assert at(sun.sunrise + timedelta(hours=1)) == 310  # halfway in mireds
    assert at(sun.sunrise + timedelta(hours=2)) == 250
    assert at(local(day, "12:00")) == 250
    assert at(sun.sunset - timedelta(hours=1)) == 310
    assert at(sun.sunset) == 370
    assert at(local(day, "23:30")) == 370


def test_a_short_winter_day_never_reaches_full_cool():
    settings = DaylightSettings(morning_end=240, evening_start=-240)
    day = date(2026, 12, 21)  # under 6 h of sun: the slopes overlap
    points = day_points(day, *HELSINKI, settings)
    middle = points.sun.sunrise + (points.sun.sunset - points.sun.sunrise) / 2
    assert 0.6 < coolness(middle, points) < 0.8
    assert max(coolness(middle + timedelta(minutes=m), points) for m in range(-90, 91, 5)) < 0.8


def test_equal_start_and_end_is_a_step():
    settings = DaylightSettings(morning_start=60, morning_end=60)
    day = date(2026, 10, 23)
    sun = sun_times(day, *HELSINKI)
    step = sun.sunrise + timedelta(hours=1)
    assert daylight_mireds(step - timedelta(seconds=1), TZ, *HELSINKI, settings) == 370
    assert daylight_mireds(step, TZ, *HELSINKI, settings) == 250


@pytest.mark.parametrize(
    "bad",
    [
        {"warm_kelvin": 4000, "cool_kelvin": 4000},
        {"cool_kelvin": 7000},
        {"morning_start": 60, "morning_end": 30},
        {"morning_start": -200},
        {"evening_end": 200},
        {"evening_start": 0, "evening_end": -30},
    ],
)
def test_daylight_settings_are_validated(bad):
    with pytest.raises(SettingsError):
        DaylightSettings(**bad).validate()
