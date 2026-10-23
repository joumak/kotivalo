"""Lamps following daylight, end to end in the service with fake lamps and a fake clock."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from kotivalo.app import Service
from kotivalo.clock import FakeClock
from kotivalo.daylight import daylight_mireds, sun_times
from kotivalo.events import LightReport, Motion
from kotivalo.ramp import kelvin_to_mired
from kotivalo.settings import DaylightSettings, Store
from kotivalo.web import make_web_app

LAMP = "00:00:00:00:00:00:00:02"
SENSOR = "00:00:00:00:00:00:00:f1"
HELSINKI = (60.17, 24.94)
DAY = datetime(2026, 10, 23, tzinfo=UTC).date()
SUNRISE = sun_times(DAY, *HELSINKI).sunrise  # 8.19 local
MORNING = SUNRISE + timedelta(hours=1)  # halfway from warm to cool


@pytest.fixture
async def setup(aiohttp_client, tmp_path):
    clock = FakeClock(MORNING)
    service = Service(Store(tmp_path), fake=True, fake_sensors=1, clock=clock)
    await service.start()
    client = await aiohttp_client(make_web_app(service))
    place = {"name": "Helsinki", "lat": HELSINKI[0], "lon": HELSINKI[1]}
    assert (await client.put("/api/weather", json=place)).status == 200
    yield service, client, clock
    await service.stop()


async def settle(service, rounds=30):
    for _ in range(rounds):
        await asyncio.sleep(0)
    await asyncio.sleep(0.6)  # switching on waits before setting the colour


def controller(service):
    return service.registry.controller(LAMP)


def expected(clock) -> int:
    return daylight_mireds(clock.now(), service_tz(), *HELSINKI, DaylightSettings())


def service_tz():
    from zoneinfo import ZoneInfo

    return ZoneInfo("Europe/Helsinki")


async def follow(service, client):
    body = {"action": "daylight", "value": 1}
    assert (await client.post(f"/api/lights/{LAMP}", json=body)).status == 200
    await settle(service)


async def tick(service, clock, minutes: float):
    clock.advance(minutes * 60)
    controller(service).last_command = -1e9  # long after our own command
    service._behaviour_changed.set()  # motion's timers
    service._daylight_changed.set()
    await settle(service)


async def test_switching_on_takes_the_warmth_of_the_moment(setup):
    service, client, clock = setup
    await follow(service, client)
    await client.post(f"/api/lights/{LAMP}", json={"action": "on"})
    await settle(service)
    assert controller(service).state.mireds == expected(clock)  # not the last one by hand
    assert 300 < expected(clock) < 320


async def test_a_lit_lamp_cools_through_the_morning_in_small_steps(setup):
    service, client, clock = setup
    await client.post(f"/api/lights/{LAMP}", json={"action": "on"})
    await settle(service)
    assert controller(service).state.mireds == kelvin_to_mired(2700)  # not following yet
    await follow(service, client)
    await tick(service, clock, 0)
    assert controller(service).state.mireds == expected(clock)
    sent = len(controller(service).light.commands())
    await tick(service, clock, 1)  # 1 mired later: not worth a command
    assert len(controller(service).light.commands()) == sent
    await tick(service, clock, 60)
    assert controller(service).state.mireds == 250  # full daylight, 4000 K
    state = await (await client.get("/api/state")).json()
    assert state["daylight"]["lights"] == [LAMP]
    assert state["daylight"]["kelvin_now"] == 4000
    assert state["daylight"]["sunrise"] == SUNRISE.isoformat()


async def test_warmth_by_hand_pauses_it_until_the_lamp_is_switched_off(setup):
    service, client, clock = setup
    await follow(service, client)
    await client.post(f"/api/lights/{LAMP}", json={"action": "on"})
    await client.post(f"/api/lights/{LAMP}", json={"action": "kelvin", "value": 2500})
    await settle(service)
    await tick(service, clock, 30)
    assert controller(service).state.mireds == kelvin_to_mired(2500)
    state = await (await client.get("/api/state")).json()
    assert state["daylight"]["paused"] == [LAMP]

    await client.post(f"/api/lights/{LAMP}", json={"action": "off"})
    await settle(service)
    assert service.state.daylight_paused == []
    await client.post(f"/api/lights/{LAMP}", json={"action": "on"})
    await settle(service)
    assert controller(service).state.mireds == expected(clock)


async def test_following_again_ends_the_pause_at_once(setup):
    service, client, clock = setup
    await follow(service, client)
    await client.post(f"/api/lights/{LAMP}", json={"action": "on"})
    await client.post(f"/api/lights/{LAMP}", json={"action": "kelvin", "value": 2500})
    await settle(service)
    controller(service).last_command = -1e9
    await follow(service, client)
    assert controller(service).state.mireds == expected(clock)


async def test_a_wall_switch_off_ends_the_pause(setup):
    service, client, clock = setup
    await follow(service, client)
    await client.post(f"/api/lights/{LAMP}", json={"action": "on"})
    await client.post(f"/api/lights/{LAMP}", json={"action": "kelvin", "value": 2500})
    await settle(service)
    controller(service).last_command = -1e9
    service.events.put_nowait(LightReport(LAMP, "on_off", False))
    await settle(service)
    assert service.state.daylight_paused == []


async def test_motion_by_day_follows_daylight_but_the_night_light_stays_warm(setup):
    service, client, clock = setup
    rule = {"lights": [LAMP], "dark_lux": None, "off_after_min": 5}
    assert (await client.put(f"/api/motion/{SENSOR}", json=rule)).status == 200
    await follow(service, client)
    service.events.put_nowait(Motion(SENSOR, True))
    await settle(service)
    assert controller(service).state.mireds == expected(clock)

    service.events.put_nowait(Motion(SENSOR, False))
    await settle(service)
    await tick(service, clock, 6)  # off by motion
    assert controller(service).state.on is False
    await client.put("/api/night", json={"start": "00:00", "end": "23:59"})
    service.events.put_nowait(Motion(SENSOR, True))
    await settle(service)
    assert service.behaviour.lamp(LAMP).profile == "night"
    await tick(service, clock, 1)
    night = controller(service).caps.clamp_mireds(kelvin_to_mired(2200))
    assert controller(service).state.mireds == night  # the night profile's own


async def test_hand_only_is_left_alone(setup):
    service, client, clock = setup
    await follow(service, client)
    await client.post(f"/api/lights/{LAMP}", json={"action": "on"})
    await settle(service)
    await client.post(f"/api/lights/{LAMP}", json={"action": "hand_only", "value": 1})
    before = controller(service).state.mireds
    await tick(service, clock, 60)
    assert controller(service).state.mireds == before


async def test_the_curve_is_validated_and_applies_at_once(setup):
    service, client, clock = setup
    await follow(service, client)
    await client.post(f"/api/lights/{LAMP}", json={"action": "on"})
    await settle(service)
    bad = {"morning_start": 60, "morning_end": 0}
    assert (await client.put("/api/daylight", json=bad)).status == 400
    controller(service).last_command = -1e9
    later = {"morning_start": 120, "morning_end": 240}  # still warm an hour after sunrise
    assert (await client.put("/api/daylight", json=later)).status == 200
    await settle(service)
    assert controller(service).state.mireds == kelvin_to_mired(2700)
    assert service.settings.daylight.lights == [LAMP]  # the curve doesn't touch the lamps


async def test_without_a_place_nothing_changes(setup):
    service, client, clock = setup
    await client.put("/api/weather", json={"lat": None, "lon": None})
    await follow(service, client)
    await client.post(f"/api/lights/{LAMP}", json={"action": "on"})
    await settle(service)
    assert controller(service).state.mireds == kelvin_to_mired(2700)  # the last by hand
    state = await (await client.get("/api/state")).json()
    assert state["daylight"]["kelvin_now"] is None
