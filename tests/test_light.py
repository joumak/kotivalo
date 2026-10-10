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
