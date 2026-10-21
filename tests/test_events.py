"""The service follows lamps: reports, announcements and polling (fake lamps)."""

import asyncio

import pytest

from kotivalo import app as app_module
from kotivalo.app import Service, poll_delay
from kotivalo.events import Announce, LightReport
from kotivalo.light import LightError
from kotivalo.settings import Store

LAMP = "00:00:00:00:00:00:00:02"


@pytest.fixture
async def service(tmp_path):
    service = Service(Store(tmp_path), fake=True)
    await service.start()
    yield service
    await service.stop()


async def settle():
    for _ in range(10):
        await asyncio.sleep(0)


async def test_a_report_updates_the_lamp_and_live_views(service):
    controller = service.registry.controller(LAMP)
    controller.last_command = -1e9  # long ago
    changed = asyncio.create_task(service.wait_change(1))
    service.events.put_nowait(LightReport(LAMP, "on_off", True))
    service.events.put_nowait(LightReport(LAMP, "current_level", 77))
    assert await changed
    await settle()
    lamp = next(x for x in service.snapshot()["lights"] if x["ieee"] == LAMP)
    assert lamp["state"]["on"] is True and lamp["state"]["level"] == 77
    assert lamp["reachable"] is True


async def test_reports_right_after_our_command_are_ignored(service):
    await service.lamp_action(LAMP, "off")
    service.events.put_nowait(LightReport(LAMP, "on_off", True))  # sent before our "off"
    await settle()
    assert service.registry.controller(LAMP).state.on is False


async def test_an_announce_reads_the_lamp(service, monkeypatch):
    monkeypatch.setattr(app_module, "ANNOUNCE_SETTLE_S", 0)
    light = service.registry.controller(LAMP).light
    light.state.on, light.state.level = True, 254  # the lamp came back on after a power cut
    service.events.put_nowait(Announce(LAMP))
    for _ in range(20):
        await asyncio.sleep(0.01)
        if service.registry.controller(LAMP).state.on:
            break
    assert service.registry.controller(LAMP).state.on is True


async def test_unknown_devices_are_ignored(service):
    service.events.put_nowait(LightReport("11:22:33:44:55:66:77:88", "on_off", True))
    service.events.put_nowait(Announce("11:22:33:44:55:66:77:88"))
    await settle()  # nothing raised, nothing changed


async def test_a_silent_lamp_is_unreachable_and_polled_less_often(service):
    controller = service.registry.controller(LAMP)
    controller.light.fail = True
    with pytest.raises(LightError):
        await service._poll_lamp(controller)
    assert controller.reachable is False and controller.failures == 1
    lamp = next(x for x in service.snapshot()["lights"] if x["ieee"] == LAMP)
    assert lamp["reachable"] is False and lamp["error"]

    controller.light.fail = False
    await service._poll_lamp(controller)
    assert controller.reachable is True and controller.failures == 0


def test_poll_backoff():
    assert [poll_delay(n) for n in range(6)] == [60, 120, 240, 480, 600, 600]


async def test_failed_setup_of_a_sleepy_device_is_retried_rarely(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from kotivalo import zigbee
    from kotivalo.clock import FakeClock
    from kotivalo.events import Seen

    clock = FakeClock(datetime(2026, 10, 12, 12, 0, tzinfo=UTC))
    service = Service(Store(tmp_path), fake=True, fake_sensors=1, clock=clock)
    await service.start()
    attempts = []

    async def fails(device):
        attempts.append(device)
        return False

    class Radio:
        def get_device(self, ieee):
            return ieee

    monkeypatch.setattr(zigbee, "configure_sensor", fails)
    service.zigbee = Radio()
    sensor = "00:00:00:00:00:00:00:f1"
    try:
        for _ in range(3):
            service.events.put_nowait(Seen(sensor))
            await settle()
        assert len(attempts) == 1
        clock.advance(app_module.CONFIGURE_RETRY_S + 1)
        service.events.put_nowait(Seen(sensor))
        await settle()
        assert len(attempts) == 2
    finally:
        service.zigbee = None
        await service.stop()


async def test_a_lamp_that_cannot_be_read_shows_what_it_last_had(tmp_path):
    from kotivalo.light import FakeLight

    first = Service(Store(tmp_path), fake=True)
    await first.start()
    await first.lamp_action(LAMP, "level", 150)
    await first.stop()  # saves the lamps' last known states

    second = Service(Store(tmp_path), fake=True)
    second._fake_lights[LAMP] = FakeLight(fail=True)  # e.g. switched off at the wall
    await second.start()
    try:
        lamp = next(x for x in second.snapshot()["lights"] if x["ieee"] == LAMP)
        assert lamp["state"]["level"] == 150 and lamp["state"]["on"] is None
        assert lamp["error"] is not None
    finally:
        await second.stop()


async def test_frames_say_when_each_device_and_the_radio_last_heard_anything(tmp_path, monkeypatch):
    """A radio that answers us but hears nothing (the XStick after a reset) shows as quiet."""
    from datetime import UTC, datetime

    from kotivalo.clock import FakeClock
    from kotivalo.events import Seen

    clock = FakeClock(datetime(2026, 10, 21, 12, 0, tzinfo=UTC))
    service = Service(Store(tmp_path), fake=True, clock=clock)
    await service.start()
    pushes = []
    monkeypatch.setattr(service, "notify", lambda: pushes.append(clock.now()))
    other = "00:00:00:00:00:00:00:01"
    start = clock.now().timestamp()
    try:
        assert service.snapshot()["radio"]["heard"] is None
        service._handle_event(Seen(LAMP))
        clock.advance(20)
        service._handle_event(Seen(other))
        assert len(pushes) == 1  # the UI hears of it at most once a minute
        clock.advance(45)
        service._handle_event(Seen(LAMP))
        assert len(pushes) == 2
        snapshot = service.snapshot()
        assert snapshot["radio"]["heard"] == start + 65
        seen = {d["ieee"]: d["last_seen"] for d in snapshot["devices"]}
        assert seen[LAMP] == start + 65 and seen[other] == start + 20
    finally:
        await service.stop()


async def test_fake_mode_has_no_radio(service):
    radio = service.snapshot()["radio"]
    assert radio["fake"] is True
    assert radio["model"] is None and radio["started"] is None


@pytest.mark.parametrize(
    ("kind", "interviewed", "set_up"),
    [
        ("joined", True, True),  # re-paired, still in zigpy's database: no new interview
        ("joined", False, False),  # new to the database (a new radio): wait for the interview
        ("initialized", True, True),
    ],
)
async def test_a_known_lamp_is_set_up_once_its_endpoints_are_known(
    service, monkeypatch, kind, interviewed, set_up
):
    from types import SimpleNamespace

    from kotivalo import zigbee
    from kotivalo.registry import Discovered

    found = Discovered(LAMP, "light", "Fake panel", "Test", 1, initialized=interviewed)
    monkeypatch.setattr(zigbee, "discovered", lambda device: found)
    setups = []

    async def setup(lamp):
        setups.append(lamp)

    monkeypatch.setattr(service, "_setup_lamp", setup)
    device = SimpleNamespace(ieee=LAMP, manufacturer="Test", model=None, is_initialized=interviewed)
    service._device_event(kind, device)
    await settle()
    assert setups == ([LAMP] if set_up else [])
