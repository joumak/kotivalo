"""Fixtures: several bulbs (a lamp's spots) acting as one lamp."""

import asyncio
from datetime import UTC, datetime

import pytest

from kotivalo.app import Service
from kotivalo.clock import FakeClock
from kotivalo.events import LightReport, Motion
from kotivalo.light import (
    FakeLight,
    FixtureLight,
    LightCaps,
    LightController,
    LightError,
    LightState,
    combined_state,
    common_caps,
)
from kotivalo.settings import Store
from kotivalo.web import make_web_app

SOLO = "00:00:00:00:00:00:00:01"  # the wake-up lamp
SPOT_A = "00:00:00:00:00:00:00:02"
SPOT_B = "00:00:00:00:00:00:00:03"
SENSOR = "00:00:00:00:00:00:00:f1"
REMOTE = "00:00:00:00:00:00:00:e1"
T0 = datetime(2026, 10, 12, 15, 0, tzinfo=UTC)  # 18:00 in Helsinki: day


def bulb(on=False, level=2, mireds=454, caps=None):
    fake = FakeLight(state=LightState(on, level, mireds))
    controller = LightController(fake, caps or LightCaps("Fake", "Test", True))
    controller.state = LightState(on, level, mireds)
    return controller, fake


# --- the parts -----------------------------------------------------------------------


async def test_a_fixture_light_sends_every_command_to_every_bulb():
    (a, fa), (b, fb) = bulb(), bulb()
    light = FixtureLight(lambda: [a, b])
    await light.set_level(200, 0)
    await light.set_ct(300)
    assert fa.commands() == fb.commands() == [("level", 200, 0), ("ct", 300)]
    assert a.state.level == b.state.level == 200


async def test_one_silent_bulb_does_not_stop_the_others_but_all_silent_fails():
    (a, fa), (b, fb) = bulb(), bulb()
    fb.fail = True
    light = FixtureLight(lambda: [a, b])
    await light.set_level(100, 0)
    assert fa.commands() == [("level", 100, 0)]
    fa.fail = True
    with pytest.raises(LightError):
        await light.set_level(120, 0)


def test_combined_state_and_caps():
    assert combined_state([LightState(True, 80, 300), LightState(True, 200, 350)]) == LightState(
        True, 200, 350
    )
    assert combined_state([LightState(False, 2, 454), LightState(False, 2, 454)]).on is False
    assert combined_state([LightState(False, 2, 454), LightState(None, None, None)]).on is None
    caps = common_caps(
        [
            LightCaps(supports_ct=True, min_mireds=250, max_mireds=454),
            LightCaps(supports_ct=True, min_mireds=200, max_mireds=400),
        ]
    )
    assert (caps.supports_ct, caps.min_mireds, caps.max_mireds) == (True, 250, 400)
    assert (
        common_caps([LightCaps(supports_ct=True), LightCaps(supports_ct=False)]).supports_ct
        is False
    )


# --- in the service ------------------------------------------------------------------


@pytest.fixture
async def setup(aiohttp_client, tmp_path):
    clock = FakeClock(T0)
    service = Service(
        Store(tmp_path), fake=True, fake_lamps=3, fake_sensors=1, fake_remotes=1, clock=clock
    )
    await service.start()
    client = await aiohttp_client(make_web_app(service))
    yield service, client, clock
    await service.stop()


async def settle():
    for _ in range(30):
        await asyncio.sleep(0)
    await asyncio.sleep(0.6)  # "on" waits before setting the warmth


async def make_fixture(client, members=(SPOT_A, SPOT_B), name="Lattiavalo"):
    body = {"name": name, "room": "Olohuone", "members": list(members)}
    response = await client.post("/api/fixtures", json=body)
    assert response.status == 200, await response.text()
    state = await response.json()
    return next(d["ieee"] for d in state["devices"] if d["kind"] == "fixture"), state


def fake(service, ieee):
    return service.registry.controllers[ieee].light


async def test_a_fixture_replaces_its_bulbs_as_one_lamp(setup):
    service, client, clock = setup
    fid, state = await make_fixture(client)
    assert [x["ieee"] for x in state["lights"]] == [SOLO, fid]
    lamp = next(x for x in state["lights"] if x["ieee"] == fid)
    assert lamp["name"] == "Lattiavalo" and lamp["members"] == [SPOT_A, SPOT_B]
    devices = {d["ieee"]: d for d in state["devices"]}
    assert devices[SPOT_A]["fixture"] == fid and devices[fid]["members"] == [SPOT_A, SPOT_B]

    await client.post(f"/api/lights/{fid}", json={"action": "level", "value": 150})
    await settle()
    for spot in (SPOT_A, SPOT_B):
        assert ("level", 150, 0.3) in fake(service, spot).commands()
    assert service.registry.controller(fid).state.on is True


async def test_the_fixture_follows_its_bulbs_reports(setup):
    service, client, clock = setup
    fid, _ = await make_fixture(client)
    for spot in (SPOT_A, SPOT_B):
        service.registry.controllers[spot].last_command = -1e9  # long ago
    service.events.put_nowait(LightReport(SPOT_A, "on_off", True))
    await settle()
    assert service.registry.controller(fid).state.on is True
    assert service.behaviour.lamp(fid).owner == "manual"  # e.g. its wall switch
    service.events.put_nowait(LightReport(SPOT_A, "on_off", False))
    await settle()
    assert service.registry.controller(fid).state.on is False
    assert service.behaviour.lamp(fid).owner == "off"


async def test_roles_pass_from_the_bulbs_to_the_fixture(setup):
    service, client, clock = setup
    await client.put(f"/api/motion/{SENSOR}", json={"lights": [SPOT_A], "dark_lux": None})
    await client.put(f"/api/remotes/{REMOTE}", json={"lights": [SPOT_B]})
    await client.post(f"/api/lights/{SPOT_A}", json={"action": "daylight", "value": 1})
    fid, _ = await make_fixture(client)
    assert service.settings.motion[0].lights == [fid]
    assert service.settings.remotes[0].lights == [fid]
    assert service.settings.daylight.lights == [fid]

    service.events.put_nowait(Motion(SENSOR, True))
    await settle()
    for spot in (SPOT_A, SPOT_B):
        assert service.registry.controllers[spot].state.on is True
    assert service.behaviour.lamp(fid).owner == "motion"


async def test_switching_a_fixture_off_fades_every_bulb(setup):
    service, client, clock = setup
    fid, _ = await make_fixture(client)
    await client.post(f"/api/lights/{fid}", json={"action": "level", "value": 150})
    await settle()
    state = await (await client.post(f"/api/lights/{fid}", json={"action": "off"})).json()
    assert next(x for x in state["lights"] if x["ieee"] == fid)["state"]["on"] is False
    await settle()
    for spot in (SPOT_A, SPOT_B):
        assert fake(service, spot).commands()[-2:] == [("fade", 2, 0.0), ("off",)]


async def test_removing_bulbs_and_fixtures(setup):
    service, client, clock = setup
    fid, _ = await make_fixture(client)
    assert (await client.put(f"/api/fixtures/{fid}", json={"members": [SPOT_A]})).status == 200
    assert service.registry.lamp_ids() == [SOLO, SPOT_B, fid]  # SPOT_B is a lamp again
    await client.post(f"/api/lights/{fid}", json={"action": "daylight", "value": 1})
    await client.delete(f"/api/devices/{SPOT_A}")  # its last bulb: the fixture goes too
    assert fid not in service.settings.devices
    assert service.settings.daylight.lights == []
    assert service.registry.lamp_ids() == [SOLO, SPOT_B]


async def test_fixtures_are_validated(setup):
    service, client, clock = setup
    fid, _ = await make_fixture(client, members=[SPOT_A])
    bad = [
        {"name": "Toinen", "members": [SPOT_A]},  # already in a fixture
        {"name": "Anturi", "members": [SENSOR]},  # not a bulb
        {"name": "Tyhjä", "members": []},
        {"name": "", "members": [SPOT_B]},
    ]
    for body in bad:
        assert (await client.post("/api/fixtures", json=body)).status == 400, body
    assert len(service.registry.fixture_ids()) == 1


async def test_the_master_switch_and_a_fixture(setup):
    service, client, clock = setup
    fid, _ = await make_fixture(client)
    await client.post(f"/api/lights/{fid}", json={"action": "level", "value": 120})
    await settle()
    await client.post("/api/master", json={"action": "off"})
    await settle()
    assert service.state.master == {fid: {"level": 120, "kelvin": 2203, "owner": "manual"}}
    await client.post("/api/master", json={"action": "on"})
    await settle()
    for spot in (SPOT_A, SPOT_B):
        assert service.registry.controllers[spot].state.level == 120


async def test_a_fixture_of_fake_bulbs_is_not_saved(setup):
    service, client, clock = setup
    fid, _ = await make_fixture(client)
    assert fid not in service.store.load_settings().devices


async def test_a_two_channel_dimmer_in_the_service(aiohttp_client, tmp_path):
    service = Service(Store(tmp_path), fake=True, fake_lamps=1, fake_dimmers=1)
    await service.start()
    try:
        client = await aiohttp_client(make_web_app(service))
        dimmer = "00:00:00:00:00:00:00:d1"
        channel = f"{dimmer}-2"
        state = await (await client.get("/api/state")).json()
        assert [x["ieee"] for x in state["lights"]] == [SOLO, dimmer, channel]
        devices = {d["ieee"]: d for d in state["devices"]}
        assert (devices[dimmer]["channel"], devices[channel]["channel"]) == (1, 2)
        assert devices[channel]["parent"] == dimmer

        body = {"action": "level", "value": 120}
        assert (await client.post(f"/api/lights/{channel}", json=body)).status == 200
        await settle()
        assert service._fake_lights[channel].commands() == [("level", 120, 0.3)]
        assert service._fake_lights[dimmer].commands() == []  # the other channel untouched

        assert (await client.delete(f"/api/devices/{channel}")).status == 200  # the whole device
        assert dimmer not in service.settings.devices and channel not in service.settings.devices
    finally:
        await service.stop()
