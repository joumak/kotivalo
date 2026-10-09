import pytest

from wakeup_light.app import Service
from wakeup_light.settings import Store
from wakeup_light.web import make_web_app


@pytest.fixture
async def client(aiohttp_client, tmp_path):
    service = Service(Store(tmp_path), fake=True)
    await service.start()
    client = await aiohttp_client(make_web_app(service))
    client.service = service
    yield client
    await service.stop()


async def test_state_and_manual_control(client):
    state = await (await client.get("/api/state")).json()
    assert state["light"]["available"] and state["light"]["caps"]["supports_ct"]

    rsp = await client.post("/api/light", json={"action": "level", "value": 128})
    assert rsp.status == 200
    assert (await rsp.json())["light"]["state"]["level"] == 128

    rsp = await client.post("/api/light", json={"action": "kelvin", "value": 2700})
    assert (await rsp.json())["light"]["state"]["kelvin"] == 2703  # 370 mired


async def test_writes_must_be_json(client):
    rsp = await client.post("/api/light", data="action=on")
    assert rsp.status == 415


async def test_invalid_alarm_is_rejected_and_valid_one_saved(client):
    alarms = [{"enabled": False, "time": "07:00"}] * 7
    bad = [{"enabled": True, "time": "25:00"}] + alarms[1:]
    assert (await client.put("/api/alarms", json={"alarms": bad})).status == 400

    good = [{"enabled": True, "time": "06:30"}] + alarms[1:]
    state = await (await client.put("/api/alarms", json={"alarms": good})).json()
    assert state["alarms"][0] == {"enabled": True, "time": "06:30"}
    assert state["upcoming"][0]["label"] == "Mon 06:30"
    assert client.service.store.load_settings().alarms[0].time == "06:30"


async def test_manual_action_stops_a_running_sunrise(client):
    state = await (await client.post("/api/sunrise/test", json={"minutes": 2})).json()
    assert state["sunrise"]["kind"] == "test"

    state = await (await client.post("/api/light", json={"action": "off"})).json()
    assert state["sunrise"] is None
    assert state["light"]["state"]["on"] is False
    assert ("stop",) in client.service.controller.light.commands()


async def test_token_protects_the_api(client):
    client.service.settings.web_token = "secret"
    assert (await client.get("/api/state")).status == 401
    rsp = await client.get("/api/state", headers={"X-Token": "secret"})
    assert rsp.status == 200
    assert (await client.get("/")).status == 200  # the page itself stays public
