"""Weather: MET Norway parsing, the client's caching manners, and the service's loop."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from aiohttp import web

from kotivalo import weather
from kotivalo.app import Service
from kotivalo.clock import FakeClock
from kotivalo.settings import Store
from kotivalo.web import make_web_app

DATA = json.loads((Path(__file__).parent / "data" / "met_compact.json").read_text())
T0 = datetime(2026, 10, 10, 13, 16, tzinfo=UTC)  # the recorded response starts at 13:00Z


def test_parse_takes_the_hourly_part():
    forecast = weather.parse_met(DATA)
    assert len(forecast.points) == 30  # the 6-hourly tail is left out
    assert forecast.updated == datetime(2026, 10, 10, 12, 29, 31, tzinfo=UTC)
    first = forecast.points[0]
    assert (first.temperature, first.symbol, first.wind, first.precipitation) == (
        7.0,
        "cloudy",
        3.0,
        0.0,
    )


def test_view_is_the_current_hour_and_the_next_24():
    view = weather.parse_met(DATA).view(T0)
    assert view["now"]["time"] == "2026-10-10T13:00:00+00:00"
    assert len(view["hours"]) == 24
    assert view["hours"][0]["time"] == "2026-10-10T14:00:00+00:00"


def test_view_is_empty_when_the_forecast_is_too_old_or_not_yet_valid():
    forecast = weather.parse_met(DATA)
    assert forecast.view(T0 - timedelta(hours=1)) is None  # before the first point
    assert forecast.view(T0 + timedelta(days=3)) is None


def test_unusable_responses_give_none():
    assert weather.parse_met({}) is None
    assert weather.parse_met({"properties": {"timeseries": [{"time": "x", "data": {}}]}}) is None
    assert weather.parse_met("not json") is None


def test_refresh_follows_expires_within_limits():
    assert weather.next_refresh(T0 + timedelta(minutes=30), T0) == 1800
    assert weather.next_refresh(T0 + timedelta(minutes=1), T0) == weather.MIN_REFRESH_S
    assert weather.next_refresh(T0 + timedelta(hours=5), T0) == weather.MAX_REFRESH_S
    assert weather.next_refresh(None, T0) == weather.MAX_REFRESH_S / 2


def test_typed_coordinates():
    assert weather.parse_coordinates("60.17, 24.94") == (60.17, 24.94)
    assert weather.parse_coordinates("60.17 24.94") == (60.17, 24.94)
    assert weather.parse_coordinates("60,17 24,94") == (60.17, 24.94)
    assert weather.parse_coordinates("Espoo") is None
    assert weather.parse_coordinates("95, 24") is None


async def test_client_identifies_itself_and_asks_only_for_changes(aiohttp_server):
    seen = []

    async def forecast(request):
        seen.append(dict(request.headers) | dict(request.query))
        if request.headers.get("If-Modified-Since"):
            return web.Response(status=304, headers={"Expires": "Sat, 10 Oct 2026 14:00:00 GMT"})
        headers = {
            "Expires": "Sat, 10 Oct 2026 13:42:03 GMT",
            "Last-Modified": "Sat, 10 Oct 2026 13:10:05 GMT",
        }
        return web.json_response(DATA, headers=headers)

    app = web.Application()
    app.router.add_get("/compact", forecast)
    server = await aiohttp_server(app)
    client = weather.MetClient(str(server.make_url("/compact")))

    data, expires = await client.fetch(60.1699, 24.9384)
    assert data == DATA and expires == datetime(2026, 10, 10, 13, 42, 3, tzinfo=UTC)
    assert seen[0]["User-Agent"].startswith("kotivalo/")
    assert (seen[0]["lat"], seen[0]["lon"]) == ("60.1699", "24.9384")

    data, expires = await client.fetch(60.1699, 24.9384)  # unchanged: 304, same data
    assert data == DATA and seen[1]["If-Modified-Since"] == "Sat, 10 Oct 2026 13:10:05 GMT"
    assert expires == datetime(2026, 10, 10, 14, 0, tzinfo=UTC)


@pytest.fixture
async def setup(aiohttp_client, tmp_path):
    clock = FakeClock(T0)
    service = Service(Store(tmp_path), clock=clock)
    service.fake = False  # the real weather path, with a stand-in fetcher; no radio is started
    calls = []

    async def fetch(lat, lon):
        calls.append((lat, lon))
        if service.weather_error:
            raise TimeoutError
        return DATA, T0 + timedelta(minutes=30)

    service.weather_error = False
    service.fetch_weather = fetch
    service._spawn(service._weather_loop())
    client = await aiohttp_client(make_web_app(service))
    yield service, client, clock, calls
    await service.stop()


async def settle():
    for _ in range(20):
        await asyncio.sleep(0)


async def test_no_place_means_no_fetch(setup):
    service, client, clock, calls = setup
    await settle()
    assert calls == []
    state = await (await client.get("/api/state")).json()
    assert state["weather"] == {"location": None, "forecast": None, "stale": True}


async def test_setting_a_place_fetches_and_shows_the_forecast(setup):
    service, client, clock, calls = setup
    body = {"name": "Helsinki", "lat": 60.16987, "lon": 24.93838}
    state = await (await client.put("/api/weather", json=body)).json()
    assert state["weather"]["location"] == {"name": "Helsinki", "lat": 60.17, "lon": 24.94}
    await settle()
    assert calls == [(60.17, 24.94)]
    state = await (await client.get("/api/state")).json()
    assert state["weather"]["forecast"]["now"]["temperature"] == 7.0
    assert state["weather"]["stale"] is False

    await client.put("/api/weather", json={"name": "Espoo", "lat": 60.21, "lon": 24.66})
    await settle()
    assert calls[-1] == (60.21, 24.66)  # a new place is fetched at once


async def test_a_failure_keeps_the_last_forecast_until_it_is_stale(setup):
    service, client, clock, calls = setup
    await client.put("/api/weather", json={"lat": 60.17, "lon": 24.94})
    await settle()
    service.weather_error = True
    delay = await service._refresh_weather()
    assert delay == 300
    assert service.weather_status()["forecast"] is not None
    clock.advance(3 * 3600 + 1)
    assert service.weather_status()["stale"] is True


async def test_weather_off_and_bad_places(setup):
    service, client, clock, calls = setup
    assert (await client.put("/api/weather", json={"lat": 91, "lon": 0})).status == 400
    assert (await client.put("/api/weather", json={"lat": "x", "lon": 0})).status == 400
    await client.put("/api/weather", json={"lat": 60.17, "lon": 24.94})
    state = await (await client.put("/api/weather", json={"lat": None})).json()
    assert state["weather"]["location"] is None and state["weather"]["forecast"] is None


async def test_place_search_in_fake_mode(aiohttp_client, tmp_path):
    service = Service(Store(tmp_path), fake=True)
    await service.start()
    try:
        client = await aiohttp_client(make_web_app(service))
        places = (await (await client.get("/api/weather/places?q=esp")).json())["places"]
        assert [p["name"] for p in places] == ["Espoo"]
        places = (await (await client.get("/api/weather/places?q=60.2, 24.7")).json())["places"]
        assert (places[0]["lat"], places[0]["lon"]) == (60.2, 24.7)
        await client.put("/api/weather", json={"name": "Espoo", "lat": 60.21, "lon": 24.66})
        await settle()
        assert service.weather_status()["forecast"] is not None  # the fake forecast
    finally:
        await service.stop()
