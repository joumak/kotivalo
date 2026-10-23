"""Pure daylight warmth: lamps that are warm around sunrise and sunset and cool by day.

The sun's times come from the sunrise equation (NOAA's simplified form, within a minute
or two at Finnish latitudes), for the home's place (the weather setting). The four points
are minutes from that day's sunrise and sunset, so the curve follows the seasons. Warmth
moves linearly in mireds between the points.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from kotivalo.ramp import kelvin_to_mired
from kotivalo.settings import DaylightSettings

J2000 = 2451545.0  # Julian date of 2000-01-01 12:00 UTC
J2000_ORDINAL = date(2000, 1, 1).toordinal()
SUN_ALTITUDE = -0.833  # degrees: the sun's upper edge on the horizon, refraction included
EARTH_TILT = 23.4397


@dataclass(frozen=True)
class SunTimes:
    sunrise: datetime | None  # UTC; None on a polar day or night
    sunset: datetime | None
    polar: str | None = None  # "day": the sun never sets; "night": it never rises


@dataclass(frozen=True)
class DayPoints:
    """One day's curve: when the light starts cooling, is fully cool, starts warming and
    is fully warm again (UTC)."""

    sun: SunTimes
    morning_start: datetime | None
    morning_end: datetime | None
    evening_start: datetime | None
    evening_end: datetime | None


def _julian_to_utc(julian: float) -> datetime:
    return datetime(2000, 1, 1, 12, tzinfo=UTC) + timedelta(days=julian - J2000)


def sun_times(day: date, lat: float, lon: float) -> SunTimes:
    """Sunrise and sunset on this date at this place (longitude east positive)."""
    n = day.toordinal() - J2000_ORDINAL  # days since 2000-01-01
    mean_noon = n - lon / 360
    anomaly = math.radians((357.5291 + 0.98560028 * mean_noon) % 360)
    centre = (
        1.9148 * math.sin(anomaly) + 0.0200 * math.sin(2 * anomaly) + 0.0003 * math.sin(3 * anomaly)
    )
    ecliptic = math.radians((math.degrees(anomaly) + centre + 180 + 102.9372) % 360)
    transit = J2000 + mean_noon + 0.0053 * math.sin(anomaly) - 0.0069 * math.sin(2 * ecliptic)
    declination = math.asin(math.sin(ecliptic) * math.sin(math.radians(EARTH_TILT)))
    phi = math.radians(lat)
    cos_hour = (math.sin(math.radians(SUN_ALTITUDE)) - math.sin(phi) * math.sin(declination)) / (
        math.cos(phi) * math.cos(declination)
    )
    if cos_hour < -1:
        return SunTimes(None, None, "day")
    if cos_hour > 1:
        return SunTimes(None, None, "night")
    half_day = math.degrees(math.acos(cos_hour)) / 360
    return SunTimes(_julian_to_utc(transit - half_day), _julian_to_utc(transit + half_day))


def day_points(day: date, lat: float, lon: float, settings: DaylightSettings) -> DayPoints:
    sun = sun_times(day, lat, lon)
    if sun.sunrise is None or sun.sunset is None:
        return DayPoints(sun, None, None, None, None)
    minutes = lambda m: timedelta(minutes=m)  # noqa: E731
    return DayPoints(
        sun,
        sun.sunrise + minutes(settings.morning_start),
        sun.sunrise + minutes(settings.morning_end),
        sun.sunset + minutes(settings.evening_start),
        sun.sunset + minutes(settings.evening_end),
    )


def _rising(now: datetime, start: datetime, end: datetime) -> float:
    """0 before start, 1 after end, linear between (a step if they are equal)."""
    if now >= end:
        return 1.0
    if now <= start:
        return 0.0
    return (now - start) / (end - start)


def coolness(now: datetime, points: DayPoints) -> float:
    """0 = warm, 1 = fully cool. On a short winter day the morning and evening slopes may
    overlap: the warmer one wins, so the light never reaches full cool."""
    if points.sun.polar is not None:
        return 1.0 if points.sun.polar == "day" else 0.0
    morning = _rising(now, points.morning_start, points.morning_end)
    evening = 1.0 - _rising(now, points.evening_start, points.evening_end)
    return min(morning, evening)


def daylight_mireds(
    now: datetime, tz: ZoneInfo, lat: float, lon: float, settings: DaylightSettings
) -> int:
    """The warmth for this moment, from the local day's curve."""
    points = day_points(now.astimezone(tz).date(), lat, lon, settings)
    warm, cool = kelvin_to_mired(settings.warm_kelvin), kelvin_to_mired(settings.cool_kelvin)
    return round(warm + (cool - warm) * coolness(now, points))
