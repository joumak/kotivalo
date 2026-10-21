import asyncio
import json

import pytest

from kotivalo.app import Service
from kotivalo.settings import Store
from kotivalo.web import make_web_app


@pytest.fixture
async def client(aiohttp_client, tmp_path):
    service = Service(Store(tmp_path), fake=True)
    await service.start()
    client = await aiohttp_client(make_web_app(service))
    client.service = service
    yield client
    await service.stop()


LAMP_1 = "00:00:00:00:00:00:00:01"  # the fake lamps of `serve --fake`
LAMP_2 = "00:00:00:00:00:00:00:02"


def lamp(state: dict, ieee: str) -> dict:
    return next(x for x in state["lights"] if x["ieee"] == ieee)


async def test_state_and_manual_control(client):
    state = await (await client.get("/api/state")).json()
    assert lamp(state, LAMP_1)["available"] and lamp(state, LAMP_1)["caps"]["supports_ct"]

    rsp = await client.post(f"/api/lights/{LAMP_1}", json={"action": "level", "value": 128})
    assert rsp.status == 200
    assert lamp(await rsp.json(), LAMP_1)["state"]["level"] == 128

    rsp = await client.post(f"/api/lights/{LAMP_1}", json={"action": "kelvin", "value": 2700})
    assert lamp(await rsp.json(), LAMP_1)["state"]["kelvin"] == 2703  # 370 mired


async def test_warmth_slider_covers_the_whole_light_range(client):
    state = await (await client.get("/api/state")).json()
    low, high = lamp(state, LAMP_1)["kelvin_range"]
    assert (high - low) % lamp(state, LAMP_1)["kelvin_step"] == 0

    for kelvin, mireds in ((high, 250), (low, 454)):  # slider ends clamp to the light's range
        body = {"action": "kelvin", "value": kelvin}
        rsp = await client.post(f"/api/lights/{LAMP_1}", json=body)
        assert lamp(await rsp.json(), LAMP_1)["state"]["mireds"] == mireds


async def test_writes_must_be_json(client):
    rsp = await client.post(f"/api/lights/{LAMP_1}", data="action=on")
    assert rsp.status == 415


async def test_invalid_alarm_is_rejected_and_valid_one_saved(client):
    alarms = [{"enabled": False, "time": "07:00"}] * 7
    bad = [{"enabled": True, "time": "25:00"}] + alarms[1:]
    assert (await client.put("/api/wakeup", json={"alarms": bad})).status == 400

    good = [{"enabled": True, "time": "06:30"}] + alarms[1:]
    state = await (await client.put("/api/wakeup", json={"alarms": good})).json()
    assert state["wakeup"]["alarms"][0] == {"enabled": True, "time": "06:30"}
    assert state["upcoming"][0]["label"] == "Mon 06:30"
    assert client.service.store.load_settings().wakeup.alarms[0].time == "06:30"


async def test_ramp_is_validated_and_saved(client):
    ramp = {"duration_min": 20, "gamma": 2, "warm_kelvin": 2200, "cool_kelvin": 3500, "hold_min": 0}
    state = await (await client.put("/api/wakeup", json={"ramp": ramp})).json()
    assert state["wakeup"]["ramp"] == ramp
    bad = {**ramp, "warm_kelvin": 5000}
    assert (await client.put("/api/wakeup", json={"ramp": bad})).status == 400


async def test_manual_action_stops_a_running_sunrise(client):
    state = await (await client.post("/api/sunrise/test", json={"minutes": 2})).json()
    assert state["sunrise"]["kind"] == "test"
    assert state["sunrise"]["light"] == LAMP_1

    state = await (await client.post(f"/api/lights/{LAMP_1}", json={"action": "off"})).json()
    assert state["sunrise"] is None
    assert lamp(state, LAMP_1)["state"]["on"] is False
    assert ("stop",) in client.service.controller.light.commands()


async def test_token_protects_the_api(client):
    client.service.settings.web_token = "secret"
    assert (await client.get("/api/state")).status == 401
    rsp = await client.get("/api/state", headers={"X-Token": "secret"})
    assert rsp.status == 200
    assert (await client.get("/")).status != 401  # the page itself stays public


async def test_version_1_endpoints_are_gone(client):
    assert (await client.post("/api/light", json={"action": "on"})).status in (404, 405)


# --- several lamps ----------------------------------------------------------------------


async def test_lists_every_lamp_with_its_role(client):
    state = await (await client.get("/api/state")).json()
    lamps = {lamp["ieee"]: lamp for lamp in state["lights"]}
    assert set(lamps) == {LAMP_1, LAMP_2}
    assert lamps[LAMP_1]["wakeup"] and not lamps[LAMP_2]["wakeup"]
    assert lamps[LAMP_2]["caps"]["supports_ct"]
    assert state["wakeup"]["light"] == LAMP_1
    assert {d["ieee"] for d in state["devices"]} == {LAMP_1, LAMP_2}


async def test_per_lamp_actions_touch_only_that_lamp(client):
    rsp = await client.post(f"/api/lights/{LAMP_2}", json={"action": "level", "value": 100})
    lamps = {lamp["ieee"]: lamp for lamp in (await rsp.json())["lights"]}
    assert lamps[LAMP_2]["state"]["level"] == 100
    assert lamps[LAMP_1]["state"]["on"] is not True

    rsp = await client.post(f"/api/lights/{LAMP_2}", json={"action": "toggle"})
    lamps = {lamp["ieee"]: lamp for lamp in (await rsp.json())["lights"]}
    assert lamps[LAMP_2]["state"]["on"] is False

    rsp = await client.post("/api/lights/nope", json={"action": "on"})
    assert rsp.status == 502


async def test_a_dragged_slider_sends_only_what_the_lamp_can_keep_up_with(client):
    light = client.service.registry.controller(LAMP_2).light
    values = list(range(10, 200, 10))
    await asyncio.gather(
        *(
            client.post(f"/api/lights/{LAMP_2}", json={"action": "level", "value": v})
            for v in values
        )
    )
    sent = [c[1] for c in light.commands() if c[0] == "level"]
    assert sent[-1] == values[-1]
    assert len(sent) <= len(values)


async def test_changing_the_wakeup_lamp_stops_its_running_sunrise(client):
    await client.post("/api/sunrise/test", json={"minutes": 2})
    state = await (await client.put("/api/wakeup", json={"light": LAMP_2})).json()
    assert state["sunrise"] is None
    assert state["wakeup"]["light"] == LAMP_2
    assert client.service.controller is client.service.registry.controller(LAMP_2)
    assert ("stop",) in client.service.registry.controller(LAMP_1).light.commands()
    # Saved straight away: the wake-up lamp stays off after a power cut, the other comes on.
    saved = client.service.store.load_settings()
    assert saved.wakeup.light is None  # fake lamps are never saved...
    assert {x["ieee"]: x["power_on"] for x in state["lights"]} == {
        LAMP_1: "on",
        LAMP_2: "previous",
    }


async def test_rename_and_remove_devices(client):
    rsp = await client.put(f"/api/devices/{LAMP_2}", json={"name": "Olohuone", "room": "Koti"})
    lamp = next(x for x in (await rsp.json())["lights"] if x["ieee"] == LAMP_2)
    assert (lamp["name"], lamp["room"]) == ("Olohuone", "Koti")
    assert (await client.put(f"/api/devices/{LAMP_2}", json={"name": " "})).status == 400

    state = await (await client.delete(f"/api/devices/{LAMP_1}")).json()
    assert [x["ieee"] for x in state["lights"]] == [LAMP_2]
    assert state["wakeup"]["light"] is None
    assert (await client.post("/api/sunrise/test", json={"minutes": 2})).status == 502


async def test_night_window(client):
    state = await (await client.put("/api/night", json={"start": "22:30", "end": "06:00"})).json()
    assert state["night"] == {"start": "22:30", "end": "06:00"}
    assert (await client.put("/api/night", json={"start": "24:00", "end": "06:00"})).status == 400
    assert client.service.settings.night.start == "22:30"


async def read_event(rsp) -> dict:
    while True:
        line = await asyncio.wait_for(rsp.content.readline(), 2)
        if line.startswith(b"data: "):
            return json.loads(line[6:])


async def test_live_updates_arrive_over_server_sent_events(client):
    rsp = await client.get("/api/events")
    assert rsp.headers["Content-Type"].startswith("text/event-stream")
    first = await read_event(rsp)
    assert first["lights"]

    await client.post(f"/api/lights/{LAMP_2}", json={"action": "level", "value": 77})
    update = await read_event(rsp)
    lamp = next(x for x in update["lights"] if x["ieee"] == LAMP_2)
    assert lamp["state"]["level"] == 77
    rsp.close()


async def test_a_vanished_viewer_ends_its_stream_quietly(client, monkeypatch, caplog):
    """A phone asleep: its connection times out, and the next write fails."""
    from aiohttp import web

    write = web.StreamResponse.write
    writes = []

    async def failing_write(self, data):
        writes.append(data)
        if len(writes) > 1:
            raise ConnectionError("Connection lost")
        await write(self, data)

    monkeypatch.setattr(web.StreamResponse, "write", failing_write)
    rsp = await client.get("/api/events")
    assert (await read_event(rsp))["lights"]
    await client.post(f"/api/lights/{LAMP_2}", json={"action": "level", "value": 77})
    for _ in range(50):
        if len(writes) > 1:
            break
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.1)
    rsp.close()
    assert len(writes) > 1
    assert not [r for r in caplog.records if r.levelname == "ERROR"]


async def test_event_stream_takes_the_token_as_a_query_parameter(client):
    client.service.settings.web_token = "secret"
    assert (await client.get("/api/events")).status == 401
    rsp = await client.get("/api/events?token=secret")
    assert rsp.status == 200
    rsp.close()
