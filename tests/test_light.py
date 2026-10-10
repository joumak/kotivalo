import asyncio

import pytest

from kotivalo.light import LatestWins, LightError


class SlowSender:
    """Records what was sent; each send waits until the test releases it."""

    def __init__(self):
        self.sent = []
        self.release = asyncio.Event()
        self.fail = False

    async def __call__(self, kind, value):
        await self.release.wait()
        self.release.clear()
        if self.fail:
            raise LightError("no ack")
        self.sent.append((kind, value))


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)


async def test_values_queued_during_a_send_collapse_to_the_newest():
    sender = SlowSender()
    queue = LatestWins(sender)
    first = asyncio.create_task(queue.submit("level", 10))
    await settle()  # 10 is now in flight
    later = [asyncio.create_task(queue.submit("level", v)) for v in (20, 30, 40)]
    await settle()

    sender.release.set()  # finish 10
    await settle()
    sender.release.set()  # finish 40; 20 and 30 were never sent
    await asyncio.wait_for(asyncio.gather(first, *later), 1)

    assert sender.sent == [("level", 10), ("level", 40)]


async def test_kinds_are_kept_separately():
    sender = SlowSender()
    queue = LatestWins(sender)
    tasks = [asyncio.create_task(queue.submit(k, v)) for k, v in [("level", 1), ("kelvin", 2700)]]
    await settle()
    tasks.append(asyncio.create_task(queue.submit("kelvin", 3000)))
    for _ in range(3):
        sender.release.set()
        await settle()
    await asyncio.wait_for(asyncio.gather(*tasks), 1)
    assert sender.sent == [("level", 1), ("kelvin", 3000)]


async def test_a_failed_send_reaches_every_waiter():
    sender = SlowSender()
    sender.fail = True
    queue = LatestWins(sender)
    task = asyncio.create_task(queue.submit("level", 5))
    await settle()
    sender.release.set()
    with pytest.raises(LightError):
        await asyncio.wait_for(task, 1)


async def test_a_cancelled_request_does_not_break_the_queue():
    sender = SlowSender()
    queue = LatestWins(sender)
    first = asyncio.create_task(queue.submit("level", 10))
    await settle()
    second = asyncio.create_task(queue.submit("level", 20))
    await settle()
    second.cancel()  # e.g. the browser went away
    sender.release.set()
    await settle()
    sender.release.set()
    await asyncio.wait_for(first, 1)
    await settle()
    assert sender.sent == [("level", 10), ("level", 20)]


def lamp(state):
    from kotivalo.light import FakeLight, LightCaps, LightController, LightState

    fake = FakeLight(state=LightState(*state))
    controller = LightController(fake, LightCaps("Fake panel", "Test", True))
    controller.state = LightState(*state)  # as the last poll or report left it
    return controller, fake


async def test_off_fades_down_then_warms_then_switches_off():
    controller, fake = lamp((True, 200, 300))
    await controller.off(park_mireds=454, park_level=2, fade_s=0.05)
    assert fake.commands() == [("fade", 2, 0.05), ("ct", 454), ("off",)]
    assert (controller.state.on, controller.state.level, controller.state.mireds) == (False, 2, 454)


async def test_an_off_lamp_is_only_told_off():
    controller, fake = lamp((False, 2, 454))
    await controller.off(park_mireds=454, park_level=2, fade_s=0.05)
    assert fake.commands() == [("off",)]


async def test_switching_off_shows_off_at_once_and_remembers_it_was_lit():
    controller, fake = lamp((True, 200, 300))
    lit = controller.switching_off()
    assert lit is True and controller.state.on is False
    await controller.off(park_mireds=454, park_level=2, fade_s=0, lit=lit)
    assert fake.commands() == [("fade", 2, 0), ("ct", 454), ("off",)]


async def test_a_failed_off_leaves_the_state_unknown():
    controller, fake = lamp((True, 200, 300))
    fake.fail = True
    with pytest.raises(LightError):
        await controller.off(park_mireds=454, park_level=2, fade_s=0)
    assert controller.state.on is None  # the next poll tells
