"""The master switch: everything off (remembering what was lit) and back on."""

import asyncio
from datetime import UTC, datetime

import pytest

from kotivalo.app import Service
from kotivalo.clock import FakeClock
from kotivalo.events import Motion
from kotivalo.settings import Store
from kotivalo.web import make_web_app

WAKEUP = "00:00:00:00:00:00:00:01"  # the first fake lamp becomes the wake-up lamp
MOTION_LAMP = "00:00:00:00:00:00:00:02"
SPARE = "00:00:00:00:00:00:00:03"
SENSOR = "00:00:00:00:00:00:00:f1"
T0 = datetime(2026, 10, 12, 15, 0, tzinfo=UTC)  # 18:00 in Helsinki: day


@pytest.fixture
async def setup(aiohttp_client, tmp_path):
    clock = FakeClock(T0)
    service = Service(Store(tmp_path), fake=True, fake_lamps=3, fake_sensors=1, clock=clock)
    await service.start()
    client = await aiohttp_client(make_web_app(service))
    await client.put(f"/api/motion/{SENSOR}", json={"lights": [MOTION_LAMP], "dark_lux": None})
    alarms = [{"enabled": d == 0, "time": "06:30"} for d in range(7)]
    await client.put("/api/wakeup", json={"alarms": alarms})
    yield service, client, clock
    await service.stop()


async def settle():
    for _ in range(30):
        await asyncio.sleep(0)
    await asyncio.sleep(0.6)  # "on" waits before setting the warmth


def state(service, ieee):
    return service.registry.controller(ieee).state


async def light_up(service, client):
    await client.post(f"/api/lights/{WAKEUP}", json={"action": "level", "value": 150})
    await client.post(f"/api/lights/{WAKEUP}", json={"action": "kelvin", "value": 3000})
    service.events.put_nowait(Motion(SENSOR, True))
    await settle()
    assert state(service, WAKEUP).on and state(service, MOTION_LAMP).on
    assert state(service, SPARE).on is not True


async def test_off_remembers_the_lit_lamps_and_leaves_alarms_alone(setup):
    service, client, clock = setup
    await light_up(service, client)
    alarms = service.settings.wakeup.alarms

    snapshot = await (await client.post("/api/master", json={"action": "off"})).json()
    assert snapshot["master"] == {"any_on": False, "remembered": [WAKEUP, MOTION_LAMP]}
    await settle()
    assert all(state(service, ieee).on is False for ieee in (WAKEUP, MOTION_LAMP))
    memory = service.store.load_state().master  # survives a restart
    assert memory[WAKEUP] == {"level": 150, "kelvin": 3003, "owner": "manual"}
    assert memory[MOTION_LAMP]["owner"] == "motion"
    assert service.settings.wakeup.alarms == alarms and service.state.skipped == []


async def test_on_brings_them_back_and_gives_motion_lamps_to_their_sensor(setup):
    service, client, clock = setup
    await light_up(service, client)
    await client.post("/api/master", json={"action": "off"})
    await settle()

    await client.post("/api/master", json={"action": "on"})
    await settle()
    assert (state(service, WAKEUP).on, state(service, WAKEUP).level) == (True, 150)
    assert state(service, WAKEUP).mireds == 333  # 3003 K
    assert service.behaviour.lamp(WAKEUP).owner == "manual"
    # The room is still occupied (and dark is not required): motion lights it again.
    assert state(service, MOTION_LAMP).on is True
    assert service.behaviour.lamp(MOTION_LAMP).owner == "motion"
    assert state(service, SPARE).on is not True


async def test_the_memory_is_kept_until_the_next_master_off(setup):
    service, client, clock = setup
    await light_up(service, client)
    await client.post("/api/master", json={"action": "off"})
    await client.post("/api/master", json={"action": "on"})
    await settle()
    await client.post(f"/api/lights/{WAKEUP}", json={"action": "off"})  # one by one
    service.events.put_nowait(Motion(SENSOR, False))
    await client.post(f"/api/lights/{MOTION_LAMP}", json={"action": "off"})
    await settle()
    await client.post("/api/master", json={"action": "off"})  # nothing lit: memory kept
    snapshot = await (await client.post("/api/master", json={"action": "on"})).json()
    await settle()
    assert snapshot["master"]["remembered"] == [WAKEUP, MOTION_LAMP]
    assert state(service, WAKEUP).level == 150


async def test_with_nothing_remembered_every_lamp_comes_on(setup):
    service, client, clock = setup
    await client.post("/api/master", json={"action": "on"})
    await settle()
    assert all(state(service, ieee).on is True for ieee in (WAKEUP, MOTION_LAMP, SPARE))


async def test_unknown_actions_are_refused(setup):
    service, client, clock = setup
    assert (await client.post("/api/master", json={"action": "toggle"})).status == 400
