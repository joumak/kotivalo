"""Firmware updates of sleepy remotes: keep offering until the remote wakes up."""

import pytest
import zigpy.exceptions
from zigpy.zcl import foundation

from kotivalo import zigbee
from kotivalo.app import Service
from kotivalo.settings import Store
from kotivalo.web import make_web_app


class Remote:
    """A stand-in zigpy device: asleep for `asleep` attempts, then it takes the update."""

    ieee = "84:2e:14:ff:fe:41:64:b9"

    def __init__(self, asleep: int, result=foundation.Status.SUCCESS, progress_then_fail=False):
        self.asleep = asleep
        self.result = result
        self.progress_then_fail = progress_then_fail
        self.attempts = 0

    async def update_firmware(self, image, progress_callback):
        self.attempts += 1
        if self.attempts <= self.asleep:
            raise zigpy.exceptions.DeliveryError("asleep")
        progress_callback(100, 200, 50.0)
        if self.progress_then_fail:
            return foundation.Status.TIMEOUT
        progress_callback(200, 200, 100.0)
        return self.result


@pytest.fixture(autouse=True)
def quick_retries(monkeypatch):
    monkeypatch.setattr(zigbee, "WAKE_RETRY_S", 0.01)


async def test_keeps_trying_until_the_remote_wakes_up():
    remote, seen = Remote(asleep=3), []
    assert await zigbee.update_firmware(remote, object(), seen.append, wake_window_s=5) == "done"
    assert remote.attempts == 4 and seen == [50.0, 100.0]


async def test_gives_up_when_the_remote_never_wakes():
    remote = Remote(asleep=10**6)
    result = await zigbee.update_firmware(remote, object(), lambda p: None, wake_window_s=0.05)
    assert result == "failed"


async def test_an_up_to_date_remote_declines_at_once():
    remote = Remote(asleep=0)

    async def declines(image, progress_callback):
        remote.attempts += 1
        return foundation.Status.NO_IMAGE_AVAILABLE

    remote.update_firmware = declines
    assert await zigbee.update_firmware(remote, object(), lambda p: None, wake_window_s=5) == "none"
    assert remote.attempts == 1


async def test_a_failure_after_it_started_is_not_retried():
    remote = Remote(asleep=0, progress_then_fail=True)
    result = await zigbee.update_firmware(remote, object(), lambda p: None, wake_window_s=5)
    assert result == "failed" and remote.attempts == 1


async def test_only_real_remotes_can_be_updated(aiohttp_client, tmp_path):
    service = Service(Store(tmp_path), fake=True, fake_remotes=1)
    await service.start()
    try:
        client = await aiohttp_client(make_web_app(service))
        remote = "00:00:00:00:00:00:00:e1"
        assert (await client.post(f"/api/remotes/{remote}/firmware", json={})).status == 400
        lamp = "00:00:00:00:00:00:00:01"
        assert (await client.post(f"/api/remotes/{lamp}/firmware", json={})).status == 400
    finally:
        await service.stop()


def test_known_remotes_have_an_image_type():
    assert zigbee.IKEA_IMAGE_TYPES["TRADFRI remote control"] == 0x11C1
