"""Local weather from MET Norway (the data behind yr.no), Locationforecast 2.0 compact.

MET's terms: identify the app in the User-Agent, use at most 4 decimals in coordinates,
fetch again only when the response has expired, and credit "MET Norway" (CC BY 4.0).
"""

from __future__ import annotations

import email.utils
import importlib.metadata
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import aiohttp

MET_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
REQUEST_TIMEOUT_S = 20
MIN_REFRESH_S = 600  # MET's data changes about every 30 min; never ask more often than this
MAX_REFRESH_S = 3600
HOURS_AHEAD = 24  # hourly points sent to the UI
NOW_MAX_AGE = timedelta(hours=2)  # older than this, the "now" point is no longer now


def user_agent() -> str:
    try:
        version = importlib.metadata.version("kotivalo")
    except importlib.metadata.PackageNotFoundError:
        version = "dev"
    return f"kotivalo/{version} https://github.com/joumak/kotivalo"


@dataclass(frozen=True)
class Point:
    time: datetime
    temperature: float
    symbol: str | None  # MET symbol code, e.g. "partlycloudy_day"
    wind: float | None = None  # m/s
    precipitation: float | None = None  # mm in the following hour

    def to_dict(self) -> dict:
        return {
            "time": self.time.isoformat(),
            "temperature": self.temperature,
            "symbol": self.symbol,
            "wind": self.wind,
            "precipitation": self.precipitation,
        }


@dataclass(frozen=True)
class Forecast:
    updated: datetime | None  # when MET computed it
    points: list[Point]  # hourly, in time order

    def view(self, now: datetime) -> dict | None:
        """What the UI shows at `now`: the current hour and the hours after it."""
        past = [p for p in self.points if p.time <= now]
        current = past[-1] if past else None
        if current is None or now - current.time > NOW_MAX_AGE:
            return None
        ahead = [p for p in self.points if p.time > now][:HOURS_AHEAD]
        return {
            "updated": self.updated.isoformat() if self.updated else None,
            "now": current.to_dict(),
            "hours": [p.to_dict() for p in ahead],
        }


def _time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def parse_met(data: object) -> Forecast | None:
    """The hourly part of a Locationforecast compact response, or None if unusable."""
    try:
        properties = data["properties"]  # type: ignore[index]
        series = properties["timeseries"]
    except (KeyError, TypeError):
        return None
    points = []
    for entry in series:
        try:
            details = entry["data"]["instant"]["details"]
            next_hour = entry["data"]["next_1_hours"]  # only in the hourly part
            point = Point(
                time=_time(entry["time"]),
                temperature=float(details["air_temperature"]),
                symbol=next_hour.get("summary", {}).get("symbol_code"),
                wind=details.get("wind_speed"),
                precipitation=next_hour.get("details", {}).get("precipitation_amount"),
            )
        except (KeyError, TypeError, ValueError):
            continue
        points.append(point)
    if not points:
        return None
    updated = properties.get("meta", {}).get("updated_at")
    return Forecast(_time(updated) if updated else None, sorted(points, key=lambda p: p.time))


def next_refresh(expires: datetime | None, now: datetime) -> float:
    """Seconds until the next fetch: when MET says the data expires, within limits."""
    if expires is None:
        return float(MAX_REFRESH_S / 2)
    seconds = (expires - now).total_seconds()
    return float(min(MAX_REFRESH_S, max(MIN_REFRESH_S, seconds)))


def _http_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


class MetClient:
    """Fetches the forecast for one place, sending If-Modified-Since on repeats."""

    def __init__(self, url: str = MET_URL):
        self.url = url
        self._place: tuple[float, float] | None = None
        self._data: dict | None = None
        self._last_modified: str | None = None

    async def fetch(self, lat: float, lon: float) -> tuple[dict, datetime | None]:
        """(the response JSON, when it expires). Raises aiohttp.ClientError, TimeoutError."""
        place = (round(lat, 4), round(lon, 4))
        headers = {"User-Agent": user_agent()}
        if place == self._place and self._last_modified and self._data is not None:
            headers["If-Modified-Since"] = self._last_modified
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_S)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            params = {"lat": str(place[0]), "lon": str(place[1])}
            async with session.get(self.url, params=params) as rsp:
                expires = _http_date(rsp.headers.get("Expires"))
                if rsp.status == 304 and place == self._place and self._data is not None:
                    return self._data, expires
                rsp.raise_for_status()
                data = await rsp.json(content_type=None)
                self._place, self._data = place, data
                self._last_modified = rsp.headers.get("Last-Modified")
                return data, expires


def parse_coordinates(text: str) -> tuple[float, float] | None:
    """'60.17, 24.94', '60.17 24.94' or '60,17 24,94' (Finnish decimal commas)."""
    text = text.strip()
    separators = r"[,;\s]+" if "." in text else r"[;\s]+"
    parts = [p for p in re.split(separators, text) if p]
    if len(parts) != 2:
        return None
    try:
        lat, lon = (float(p.replace(",", ".").rstrip(".")) for p in parts)
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


async def search_places(query: str, language: str = "fi", url: str = GEOCODE_URL) -> list[dict]:
    """Places matching `query` (Open-Meteo's geocoder, GeoNames data), or the typed
    coordinates themselves. Raises aiohttp.ClientError, TimeoutError."""
    coordinates = parse_coordinates(query)
    if coordinates is not None:
        lat, lon = coordinates
        return [{"name": "", "region": "", "country": "", "lat": lat, "lon": lon}]
    if len(query.strip()) < 2:
        return []
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_S)
    headers = {"User-Agent": user_agent()}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        params = {"name": query.strip(), "count": "5", "language": language, "format": "json"}
        async with session.get(url, params=params) as rsp:
            rsp.raise_for_status()
            data = await rsp.json(content_type=None)
    return [
        {
            "name": r.get("name", ""),
            "region": r.get("admin1", ""),
            "country": r.get("country", ""),
            "lat": r["latitude"],
            "lon": r["longitude"],
        }
        for r in data.get("results", [])
        if "latitude" in r and "longitude" in r
    ]


FAKE_SYMBOLS = ["partlycloudy", "cloudy", "lightrain", "rain", "cloudy", "fair", "clearsky"]


def fake_forecast(now: datetime) -> Forecast:
    """A believable forecast for `serve --fake`: no network, the same every day."""
    start = now.replace(minute=0, second=0, microsecond=0)
    points = []
    for i in range(-1, HOURS_AHEAD + 6):
        time = start + timedelta(hours=i)
        hour = time.hour
        base = FAKE_SYMBOLS[(hour // 3) % len(FAKE_SYMBOLS)]
        variant = "_day" if 6 <= hour < 20 else "_night"
        symbol = base if base in ("cloudy", "lightrain", "rain") else base + variant
        temperature = round(6 + 4 * math.sin((hour - 9) / 24 * 2 * math.pi), 1)
        points.append(Point(time, temperature, symbol, 3.0, 0.4 if "rain" in base else 0.0))
    return Forecast(start, points)
