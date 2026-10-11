"""Firmware updates of sleepy remotes: keep offering until the remote wakes up."""

import pytest
import zigpy.exceptions
from zigpy.zcl import foundation

from kotivalo import zigbee
from kotivalo.app import Service
from kotivalo.settings import Store
from kotivalo.web import make_web_app


class Remote:
    """A stand-in zigpy device: asleep for `asleep` offers, then it takes the update."""

    ieee = "84:2e:14:ff:fe:41:64:b9"

    def __init__(self, asleep: int, result=foundation.Status.SUCCESS, progress_then_fail=False):
        self.asleep = asleep
        self.result = result
        self.progress_then_fail = progress_then_fail
        self.attempts = 0
        self.ota_in_progress = False
        self.ota_flags = []  # ota_in_progress during each attempt

    async def attempt(self, device, image, progress):
        self.attempts += 1
        self.ota_flags.append(self.ota_in_progress)
        if self.attempts <= self.asleep:
            raise zigpy.exceptions.DeliveryError("asleep")
        progress(100, 200)
        if self.progress_then_fail:
            return foundation.Status.TIMEOUT
        progress(200, 200)
        return self.result


@pytest.fixture(autouse=True)
def quick_retries(monkeypatch):
    monkeypatch.setattr(zigbee, "WAKE_RETRY_S", 0.01)


async def update(remote, seen=None, window=5):
    return await zigbee.update_firmware(
        remote, object(), (seen if seen is not None else []).append, window, attempt=remote.attempt
    )


async def test_keeps_offering_until_the_remote_takes_it():
    remote, seen = Remote(asleep=3), []
    assert await update(remote, seen) == "done"
    assert remote.attempts == 4 and seen == [50.0, 100.0]


async def test_zigpy_never_says_no_update_between_offers():
    remote = Remote(asleep=3)
    await update(remote)
    assert remote.ota_flags == [True] * 4  # its own OTA handler stays quiet throughout
    assert remote.ota_in_progress is False  # and is back afterwards


async def test_gives_up_when_the_remote_never_wakes():
    assert await update(Remote(asleep=10**6), window=0.05) == "failed"


async def test_an_up_to_date_remote_declines_at_once():
    remote = Remote(asleep=0, result=foundation.Status.NO_IMAGE_AVAILABLE)
    assert await update(remote) == "none" and remote.attempts == 1


async def test_a_failure_after_it_started_is_not_retried():
    remote = Remote(asleep=0, progress_then_fail=True)
    assert await update(remote) == "failed" and remote.attempts == 1


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
