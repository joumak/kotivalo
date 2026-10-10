"""Remote buttons end to end in the service, with fake lamps and a fake remote."""

import asyncio
from datetime import UTC, datetime

import pytest

from kotivalo.app import Service
from kotivalo.clock import FakeClock
from kotivalo.events import Battery, Button
from kotivalo.settings import Store
from kotivalo.web import make_web_app

LAMP = "00:00:00:00:00:00:00:02"
OTHER = "00:00:00:00:00:00:00:01"
REMOTE = "00:00:00:00:00:00:00:e1"
T0 = datetime(2026, 10, 12, 15, 0, tzinfo=UTC)


@pytest.fixture
async def setup(aiohttp_client, tmp_path):
    clock = FakeClock(T0)
    service = Service(Store(tmp_path), fake=True, fake_remotes=1, clock=clock)
    await service.start()
    client = await aiohttp_client(make_web_app(service))
    assert (await client.put(f"/api/remotes/{REMOTE}", json={"lights": [LAMP]})).status == 200
    yield service, client
    await service.stop()


async def press(service, action):
    service.events.put_nowait(Button(REMOTE, action))
    for _ in range(30):
        await asyncio.sleep(0)
    await asyncio.sleep(0.6)  # "on" waits before setting the warmth


def lamp(service, ieee=LAMP):
    return service.registry.controller(ieee)


async def test_on_restores_the_last_manual_setting_and_off_switches_off(setup):
    service, client = setup
    await client.post(f"/api/lights/{LAMP}", json={"action": "level", "value": 100})
    await client.post(f"/api/lights/{LAMP}", json={"action": "kelvin", "value": 3000})
    await press(service, "off")
    assert lamp(service).state.on is False
    assert service.behaviour.lamp(LAMP).owner == "off"

    await press(service, "on")
    assert lamp(service).state.on is True
    assert lamp(service).state.level == 100
    assert lamp(service).light.commands()[-2:] == [("level", 100, 0), ("ct", 333)]
    assert service.behaviour.lamp(LAMP).owner == "manual"
    assert lamp(service, OTHER).state.on is not True  # not controlled by this remote


async def test_toggle_switches_all_off_if_any_is_on(setup):
    service, client = setup
    await client.put(f"/api/remotes/{REMOTE}", json={"lights": [LAMP, OTHER]})
    await client.post(f"/api/lights/{LAMP}", json={"action": "on"})
    await press(service, "toggle")
    assert lamp(service).state.on is False and lamp(service, OTHER).state.on is False
    await press(service, "toggle")
    assert lamp(service).state.on is True and lamp(service, OTHER).state.on is True


async def test_holding_dims_natively_and_remembers_where_it_stopped(setup):
    service, client = setup
    await press(service, "brighter_hold")
    assert ("move", True, 85) in lamp(service).light.commands()
    await press(service, "dim_stop")
    assert lamp(service).light.commands()[-1] == ("stop",)
    assert service.settings.lights[LAMP].last_manual.level == 254
    assert service.behaviour.lamp(LAMP).owner == "manual"


async def test_dimming_an_off_lamp_does_nothing(setup):
    service, client = setup
    await press(service, "dimmer_hold")
    await press(service, "dimmer")
    await press(service, "warmer")
    assert lamp(service).light.commands() == []


async def test_steps_and_arrows(setup):
    service, client = setup
    await client.post(f"/api/lights/{LAMP}", json={"action": "level", "value": 100})
    await client.post(f"/api/lights/{LAMP}", json={"action": "kelvin", "value": 3000})  # 333
    await press(service, "brighter")
    assert lamp(service).state.level == 151
    await press(service, "warmer")
    assert lamp(service).state.mireds == 373  # 333 + 40
    await press(service, "cooler")
    assert lamp(service).state.mireds == 333


async def test_held_arrow_repeats_until_released(setup):
    service, client = setup
    await client.post(f"/api/lights/{LAMP}", json={"action": "level", "value": 100})
    await client.post(f"/api/lights/{LAMP}", json={"action": "kelvin", "value": 4000})  # 250
    await press(service, "warmer_hold")
    await asyncio.sleep(0.5)
    await press(service, "arrow_stop")
    after = lamp(service).state.mireds
    assert after >= 250 + 2 * 40
    await asyncio.sleep(0.5)
    assert lamp(service).state.mireds == after


async def test_presses_and_battery_show_in_the_snapshot(setup):
    service, client = setup
    await client.delete(f"/api/remotes/{REMOTE}")
    service.events.put_nowait(Battery(REMOTE, 87.5))
    await press(service, "on")
    assert lamp(service).state.on is not True  # no lamps: only shown
    remote = (await (await client.get("/api/state")).json())["remotes"][0]
    assert remote["name"] == "STYRBAR 00e1"
    assert remote["last_action"] == "on" and remote["last_press"] is not None
    assert remote["battery"] == 87.5 and remote["lights"] == []


async def test_remote_settings_are_validated(setup):
    service, client = setup
    assert (await client.put(f"/api/remotes/{LAMP}", json={"lights": []})).status == 400
    bad = {"lights": ["00:00:00:00:00:00:00:f1"]}
    assert (await client.put(f"/api/remotes/{REMOTE}", json=bad)).status == 400


async def test_fake_button_event(setup):
    service, client = setup
    body = {"type": "button", "ieee": REMOTE, "value": "on"}
    assert (await client.post("/api/fake/event", json=body)).status == 200
    await asyncio.sleep(0.6)
    assert lamp(service).state.on is True
