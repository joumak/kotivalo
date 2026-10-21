"""Smart plugs (IKEA TRETAKT): lamps that only switch on and off."""

import asyncio
from datetime import UTC, datetime

import pytest

from kotivalo.app import Service
from kotivalo.clock import FakeClock
from kotivalo.events import Button, Motion
from kotivalo.light import FakeLight, LightCaps, LightController, LightState, common_caps
from kotivalo.settings import Store
from kotivalo.web import make_web_app

LAMP = "00:00:00:00:00:00:00:01"
PLUG = "00:00:00:00:00:00:00:c1"
SENSOR = "00:00:00:00:00:00:00:f1"
REMOTE = "00:00:00:00:00:00:00:e1"
T0 = datetime(2026, 10, 12, 15, 0, tzinfo=UTC)  # 18:00 in Helsinki: day


async def test_a_plug_takes_any_brightness_as_on_and_switches_off_plainly():
    fake = FakeLight(caps=LightCaps("TRETAKT", "IKEA", dimmable=False), state=LightState(False))
    controller = LightController(fake, fake.caps)
    await controller.set_level(150, 0.3)  # motion, "on", a remote's "brighter"
    await controller.fade(2, 0.5)
    await controller.move(True, 85)  # a held "brighter"
    await controller.stop()
    await controller.set_ct(300)
    await controller.off(park_mireds=454, park_level=2, fade_s=0.5)
    assert fake.commands() == [("on",), ("on",), ("off",)]
    assert controller.state.on is False


def test_a_fixture_dims_only_if_every_bulb_can():
    assert common_caps([LightCaps(supports_ct=True), LightCaps(dimmable=False)]).dimmable is False
    assert common_caps([LightCaps(), LightCaps()]).dimmable is True


@pytest.fixture
async def setup(aiohttp_client, tmp_path):
    clock = FakeClock(T0)
    service = Service(
        Store(tmp_path),
        fake=True,
        fake_lamps=1,
        fake_sensors=1,
        fake_remotes=1,
        fake_plugs=1,
        clock=clock,
    )
    await service.start()
    client = await aiohttp_client(make_web_app(service))
    yield service, client, clock
    await service.stop()


async def settle():
    for _ in range(30):
        await asyncio.sleep(0)
    await asyncio.sleep(0.6)  # "on" waits before setting the warmth


def plug(service):
    return service._fake_lights[PLUG]


def state(service):
    return service.registry.controller(PLUG).state


async def test_a_plug_is_a_lamp_that_cannot_dim(setup):
    service, client, clock = setup
    snapshot = await (await client.get("/api/state")).json()
    lamp = next(x for x in snapshot["lights"] if x["ieee"] == PLUG)
    assert lamp["caps"]["dimmable"] is False and lamp["caps"]["supports_ct"] is False
    assert service.settings.wakeup.light == LAMP  # never a plug


async def test_a_lamp_found_not_to_dim_gets_the_plug_power_on(setup):
    """A plug once taken for a dimmable lamp (the TRETAKT lists Level Control) is put
    right at the next start, and then keeps its state over a power cut."""
    service, _, _ = setup
    service.registry.set_caps(PLUG, LightCaps("TRETAKT Smart plug", "IKEA of Sweden"))
    service.settings.light_settings(PLUG).power_on = "on"
    written = []

    async def set_power_on(previous):
        written.append(previous)

    plug(service).set_power_on = set_power_on
    await service._refresh_all()
    await settle()
    assert service.registry.controller(PLUG).caps.dimmable is False
    assert service.settings.light_settings(PLUG).power_on == "previous"
    assert written == [True]
    await service._refresh_all()  # nothing changed this time
    await settle()
    assert written == [True]


async def test_switching_a_plug_sends_only_on_and_off(setup):
    service, client, clock = setup
    for action in ("on", "off", "toggle"):
        response = await client.post(f"/api/lights/{PLUG}", json={"action": action})
        assert response.status == 200, await response.text()
        await settle()
    assert plug(service).commands() == [("on",), ("off",), ("on",)]
    assert state(service).on is True


async def test_motion_and_a_remote_switch_a_plug(setup):
    service, client, clock = setup
    await client.put(f"/api/motion/{SENSOR}", json={"lights": [PLUG], "dark_lux": None})
    service.events.put_nowait(Motion(SENSOR, True))
    await settle()
    assert state(service).on is True and service.behaviour.lamp(PLUG).owner == "motion"

    await client.put(f"/api/remotes/{REMOTE}", json={"lights": [PLUG]})
    for action in ("off", "brighter", "dimmer", "brighter_hold", "dim_stop", "warmer"):
        service.events.put_nowait(Button(REMOTE, action))
        await settle()
    assert state(service).on is True  # "brighter" switched it back on; the rest did nothing
    assert set(plug(service).commands()) == {("on",), ("off",)}


async def test_the_master_switch_brings_a_plug_back(setup):
    service, client, clock = setup
    await client.post(f"/api/lights/{PLUG}", json={"action": "on"})
    await settle()
    await client.post("/api/master", json={"action": "off"})
    await settle()
    assert state(service).on is False
    await client.post("/api/master", json={"action": "on"})
    await settle()
    assert state(service).on is True


async def test_a_plug_cannot_be_the_wake_up_lamp(setup):
    service, client, clock = setup
    response = await client.put("/api/wakeup", json={"light": PLUG})
    assert response.status == 400
    assert service.settings.wakeup.light == LAMP


async def test_a_plug_keeps_its_state_over_a_power_cut(setup):
    service, client, clock = setup
    assert service._set_power_on_policy(PLUG) is True  # "previous": a cut at night keeps it off
    assert service.settings.light_settings(PLUG).power_on == "previous"
    assert service._set_power_on_policy(LAMP) is True  # the wake-up lamp, as before
