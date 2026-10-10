"""Motion control end to end in the service, with fake lamps, a fake sensor and a fake clock."""

import asyncio
from datetime import UTC, datetime

import pytest

from kotivalo.app import Service
from kotivalo.clock import FakeClock
from kotivalo.events import LightReport, Lux, Motion
from kotivalo.settings import Store
from kotivalo.web import make_web_app

LAMP = "00:00:00:00:00:00:00:02"
SENSOR = "00:00:00:00:00:00:00:f1"
T0 = datetime(2026, 10, 12, 15, 0, tzinfo=UTC)  # 18:00 in Helsinki: day


@pytest.fixture
async def setup(aiohttp_client, tmp_path):
    clock = FakeClock(T0)
    service = Service(Store(tmp_path), fake=True, fake_sensors=1, clock=clock)
    await service.start()
    client = await aiohttp_client(make_web_app(service))
    rule = {"lights": [LAMP], "dark_lux": 30, "off_after_min": 5}
    assert (await client.put(f"/api/motion/{SENSOR}", json=rule)).status == 200
    yield service, client, clock
    await service.stop()


async def settle(service, rounds=30):
    for _ in range(rounds):
        await asyncio.sleep(0)
    await asyncio.sleep(0.6)  # the switch-on waits before setting the colour


def lamp_state(service):
    return service.registry.controller(LAMP).state


def commands(service):
    return service.registry.controller(LAMP).light.commands()


async def test_motion_switches_on_and_the_empty_room_switches_off(setup):
    service, client, clock = setup
    service.events.put_nowait(Motion(SENSOR, True))
    await settle(service)
    assert lamp_state(service).on is True and lamp_state(service).level == 254
    assert ("ct", 370) in commands(service)  # day profile 2700 K

    service.events.put_nowait(Motion(SENSOR, False))
    await settle(service)
    clock.advance(4 * 60)
    service._behaviour_changed.set()
    await settle(service)
    assert lamp_state(service).on is True  # not yet

    clock.advance(61)
    service._behaviour_changed.set()
    await settle(service)
    assert lamp_state(service).on is False
    assert commands(service)[-1] == ("off",)


async def test_night_gives_the_night_light(setup):
    service, client, clock = setup
    await client.put("/api/night", json={"start": "17:00", "end": "07:00"})
    service.events.put_nowait(Motion(SENSOR, True))
    await settle(service)
    assert lamp_state(service).level == 13
    state = await (await client.get("/api/state")).json()
    lamp = next(x for x in state["lights"] if x["ieee"] == LAMP)
    assert (lamp["owner"], lamp["profile"]) == ("motion", "night")


async def test_bright_room_stays_dark(setup):
    service, client, clock = setup
    service.events.put_nowait(Lux(SENSOR, 400))
    service.events.put_nowait(Motion(SENSOR, True))
    await settle(service)
    assert lamp_state(service).on is not True


async def test_manual_wins_over_motion(setup):
    service, client, clock = setup
    service.events.put_nowait(Motion(SENSOR, True))
    await settle(service)
    await client.post(f"/api/lights/{LAMP}", json={"action": "level", "value": 100})
    service.events.put_nowait(Motion(SENSOR, False))
    await settle(service)
    clock.advance(30 * 60)
    service._behaviour_changed.set()
    await settle(service)
    assert lamp_state(service).on is True
    assert service.behaviour.lamp(LAMP).owner == "manual"
    assert service.settings.lights[LAMP].last_manual.level == 100


async def test_a_wall_switch_is_followed(setup):
    service, client, clock = setup
    service.events.put_nowait(Motion(SENSOR, True))
    await settle(service)
    service.registry.controller(LAMP).last_command = -1e9  # long after our command
    service.events.put_nowait(LightReport(LAMP, "on_off", False))  # power cut at the wall
    await settle(service)
    assert service.behaviour.lamp(LAMP).owner == "off"


async def test_owners_survive_a_restart(setup, tmp_path):
    service, client, clock = setup
    service.events.put_nowait(Motion(SENSOR, True))
    await settle(service)
    assert service.store.load_state().behaviour[LAMP]["owner"] == "motion"


async def test_sensor_and_owner_in_the_snapshot(setup):
    service, client, clock = setup
    service.events.put_nowait(Lux(SENSOR, 12.5))
    service.events.put_nowait(Motion(SENSOR, True))
    await settle(service)
    state = await (await client.get("/api/state")).json()
    sensor = state["sensors"][0]
    assert sensor["ieee"] == SENSOR and sensor["occupied"] is True and sensor["lux"] == 12.5
    assert sensor["rule"]["lights"] == [LAMP]
    lamp = next(x for x in state["lights"] if x["ieee"] == LAMP)
    assert lamp["owner"] == "motion" and lamp["has_motion"] is True


async def test_motion_rules_are_validated(setup):
    service, client, clock = setup
    other = {"lights": ["00:00:00:00:00:00:00:01"], "night": {"level": 1, "kelvin": 2200}}
    assert (await client.put(f"/api/motion/{SENSOR}", json=other)).status == 400  # level 1
    assert (await client.put(f"/api/motion/{LAMP}", json={"lights": []})).status == 400
    assert (await client.delete(f"/api/motion/{SENSOR}")).status == 200
    assert service.settings.motion == []


async def test_fake_events_endpoint_exists_only_in_fake_mode(setup, aiohttp_client, tmp_path):
    service, client, clock = setup
    body = {"type": "motion", "ieee": SENSOR, "value": True}
    state = await (await client.post("/api/fake/event", json=body)).json()
    assert state["sensors"][0]["occupied"] is True

    real = Service(Store(tmp_path / "real"))  # not started: only the routes matter
    real_client = await aiohttp_client(make_web_app(real))
    assert (await real_client.post("/api/fake/event", json=body)).status in (404, 405)


async def test_let_motion_control_a_lamp_again(setup):
    service, client, clock = setup
    service.events.put_nowait(Motion(SENSOR, True))
    await settle(service)
    await client.post(f"/api/lights/{LAMP}", json={"action": "off"})  # off by hand, in the room
    service.events.put_nowait(Motion(SENSOR, True))
    await settle(service)
    assert lamp_state(service).on is False and service.behaviour.motion_paused(LAMP, clock.now())

    response = await client.post(f"/api/lights/{LAMP}", json={"action": "auto"})
    assert response.status == 200
    await settle(service)
    assert lamp_state(service).on is True  # the room is occupied and dark
    lamp = next(x for x in (await response.json())["lights"] if x["ieee"] == LAMP)
    assert lamp["owner"] == "motion" and lamp["motion_paused"] is False


async def test_let_motion_control_needs_a_sensor(setup):
    service, client, clock = setup
    other = "00:00:00:00:00:00:00:01"
    assert (await client.post(f"/api/lights/{other}", json={"action": "auto"})).status == 400


async def test_off_from_the_app_answers_at_once_and_fades_out_after(setup, monkeypatch):
    from kotivalo import app

    service, client, clock = setup
    monkeypatch.setattr(app, "OFF_FADE_S", 0.4)
    await client.post(f"/api/lights/{LAMP}", json={"action": "level", "value": 200})
    await settle(service)
    response = await client.post(f"/api/lights/{LAMP}", json={"action": "off"})
    lamp = next(x for x in (await response.json())["lights"] if x["ieee"] == LAMP)
    assert lamp["state"]["on"] is False  # shown off at once
    assert ("off",) not in commands(service)  # while the fade is still running
    await asyncio.sleep(0.6)
    assert commands(service)[-2:] == [("fade", 2, 0.4), ("off",)]  # keeps its warmth


async def test_only_the_wake_up_lamp_turns_warm_before_off(setup):
    service, client, clock = setup
    wakeup = service.settings.wakeup.light
    assert wakeup is not None and wakeup != LAMP
    await client.post(f"/api/lights/{wakeup}", json={"action": "level", "value": 200})
    await client.post(f"/api/lights/{wakeup}", json={"action": "kelvin", "value": 4000})
    await client.post(f"/api/lights/{wakeup}", json={"action": "off"})
    await settle(service)
    fake = service.registry.controller(wakeup).light
    assert fake.commands()[-3:] == [("fade", 2, 0.0), ("ct", 454), ("off",)]


async def hand_only(client, value):
    body = {"action": "hand_only", "value": value}
    state = await (await client.post(f"/api/lights/{LAMP}", json=body)).json()
    return next(x for x in state["lights"] if x["ieee"] == LAMP)["hand_only"]


async def test_hand_only_from_the_app(setup):
    service, client, clock = setup
    assert await hand_only(client, 1) is True
    service.events.put_nowait(Motion(SENSOR, True))
    await settle(service)
    assert lamp_state(service).on is not True  # motion leaves it alone

    assert await hand_only(client, 0) is False
    await settle(service)
    assert lamp_state(service).on is True  # released: back to motion, the room is occupied
    assert (await client.post(f"/api/lights/{LAMP}", json={"action": "hand_only"})).status == 400
