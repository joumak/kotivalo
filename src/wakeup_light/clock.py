"""Wall-clock access, swappable for tests, plus the NTP sync check."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

LOGGER = logging.getLogger(__name__)

MAX_SLEEP_CHUNK_S = 15  # re-check the wall clock often, so NTP steps can't make us late


class Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    async def sleep_until(self, when: datetime) -> None:
        while (remaining := (when - self.now()).total_seconds()) > 0:  # noqa: ASYNC110 (wall-clock poll)
            await asyncio.sleep(min(remaining, MAX_SLEEP_CHUNK_S))


class FakeClock(Clock):
    """Time only moves when something sleeps (or the test advances it)."""

    def __init__(self, start: datetime):
        self.t = start

    def now(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)

    async def sleep(self, seconds: float) -> None:
        self.advance(seconds)
        await asyncio.sleep(0)

    async def sleep_until(self, when: datetime) -> None:
        if when > self.t:
            self.t = when
        await asyncio.sleep(0)


async def ntp_synchronized() -> bool | None:
    """True/False from systemd-timesyncd, or None where timedatectl is unavailable."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "timedatectl", "show", "-p", "NTPSynchronized", "--value",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )  # fmt: skip
    except OSError:
        return None
    try:
        # asyncio.timeout, not wait_for: on Python 3.11 wait_for can swallow a
        # cancellation that arrives as the call finishes, leaving the caller running.
        async with asyncio.timeout(5):
            out, _ = await proc.communicate()
    except TimeoutError:
        return None
    finally:
        if proc.returncode is None:
            proc.kill()
    value = out.decode().strip()
    return {"yes": True, "no": False}.get(value)
