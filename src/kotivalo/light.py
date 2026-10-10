"""The light abstraction: what the sunrise engine and web UI need from a bulb."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Protocol

LOGGER = logging.getLogger(__name__)

MIN_LEVEL = 2  # IKEA FLOALT turns off at level 1
MAX_LEVEL = 254


class LightError(Exception):
    """A command did not reach the light (delivery failure, timeout, no device)."""


@dataclass
class LightCaps:
    model: str | None = None
    manufacturer: str | None = None
    supports_ct: bool = False
    min_mireds: int = 250
    max_mireds: int = 454

    def clamp_mireds(self, mireds: int) -> int:
        return max(self.min_mireds, min(self.max_mireds, round(mireds)))


@dataclass
class LightState:
    on: bool | None = None
    level: int | None = None
    mireds: int | None = None


class Light(Protocol):
    async def set_level(self, level: int, transition_s: float = 0) -> None:
        """Move to level (2..254), switching on if needed."""

    async def set_ct(self, mireds: int) -> None:
        """Set colour temperature instantly (IKEA freezes on CT transitions)."""

    async def on(self) -> None: ...

    async def off(self) -> None:
        """Switch off without a transition (IKEA can stay on after a transitioned off)."""

    async def stop(self) -> None:
        """Abort any running transition."""

    async def read_state(self) -> LightState: ...

    async def read_caps(self) -> LightCaps: ...


@dataclass
class FakeLight:
    """In-memory light for tests and `serve --fake`; records every call."""

    caps: LightCaps = field(default_factory=lambda: LightCaps("Fake panel", "Test", True))
    state: LightState = field(default_factory=lambda: LightState(False, MIN_LEVEL, 454))
    calls: list[tuple] = field(default_factory=list)
    clock: object | None = None  # anything with now(); defaults to time.monotonic
    fail: bool = False

    def _record(self, *call) -> None:
        if self.fail:
            raise LightError("fake failure")
        stamp = self.clock.now() if self.clock else time.monotonic()
        self.calls.append((stamp, *call))
        LOGGER.debug("FakeLight %s", call)

    async def set_level(self, level: int, transition_s: float = 0) -> None:
        self._record("level", level, transition_s)
        self.state.on, self.state.level = True, level

    async def set_ct(self, mireds: int) -> None:
        self._record("ct", mireds)
        self.state.mireds = mireds

    async def on(self) -> None:
        self._record("on")
        self.state.on = True

    async def off(self) -> None:
        self._record("off")
        self.state.on = False

    async def stop(self) -> None:
        self._record("stop")

    async def read_state(self) -> LightState:
        return LightState(**asdict(self.state))

    async def read_caps(self) -> LightCaps:
        return self.caps

    def commands(self) -> list[tuple]:
        """Calls without timestamps, for assertions."""
        return [call[1:] for call in self.calls]


class LightController:
    """Serialises commands to one light and keeps the last commanded state.

    The lock keeps a CT-then-level pair from interleaving with another command.
    """

    def __init__(self, light: Light | None, caps: LightCaps | None = None):
        self.light = light
        self.caps = caps or LightCaps()
        self.state = LightState()
        self.lock = asyncio.Lock()
        self.last_error: str | None = None

    @property
    def available(self) -> bool:
        return self.light is not None

    def _require(self) -> Light:
        if self.light is None:
            raise LightError("No light selected. Pair one and choose it in the device list.")
        return self.light

    async def _run(self, coro_factory) -> None:
        try:
            await coro_factory()
            self.last_error = None
        except LightError as exc:
            self.last_error = str(exc)
            raise

    async def set_level(self, level: int, transition_s: float = 0) -> None:
        light = self._require()
        level = max(MIN_LEVEL, min(MAX_LEVEL, round(level)))
        await self._run(lambda: light.set_level(level, transition_s))
        self.state.on, self.state.level = True, level

    async def set_ct(self, mireds: int) -> None:
        light = self._require()
        if not self.caps.supports_ct:
            return
        mireds = self.caps.clamp_mireds(mireds)
        await self._run(lambda: light.set_ct(mireds))
        self.state.mireds = mireds

    async def on(self) -> None:
        light = self._require()
        await self._run(light.on)
        self.state.on = True

    async def off(self, park_mireds: int | None = None) -> None:
        """Switch off; first 'park' at a warm CT so the next switch-on starts warm."""
        light = self._require()
        if park_mireds is not None and self.caps.supports_ct and self.state.on is not False:
            await self.set_ct(park_mireds)
            await asyncio.sleep(0.5)
        await self._run(light.off)
        self.state.on = False

    async def stop(self) -> None:
        light = self._require()
        await self._run(light.stop)

    async def refresh(self) -> LightState:
        light = self._require()
        state = await light.read_state()
        self.state = state
        return state


class LatestWins:
    """Sends the newest value per kind ("level", "kelvin") to one lamp.

    While a command is in flight, newer values replace any pending one, so a
    dragged slider never builds a queue behind the slow radio. Each submit()
    returns once its value, or a newer one of the same kind, has been sent.
    """

    def __init__(self, send):
        self._send = send  # async (kind, value) -> None
        self._pending: dict[str, tuple[object, list[asyncio.Future]]] = {}
        self._worker: asyncio.Task | None = None

    async def submit(self, kind: str, value) -> None:
        future = asyncio.get_running_loop().create_future()
        waiters = self._pending.get(kind, (None, []))[1]
        self._pending[kind] = (value, [*waiters, future])
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run())
        await future

    async def _run(self) -> None:
        while self._pending:
            kind = next(iter(self._pending))
            value, waiters = self._pending.pop(kind)
            error = None
            try:
                await self._send(kind, value)
            except Exception as exc:  # noqa: BLE001 - handed to every waiter
                error = exc
            for waiter in waiters:
                if waiter.done():
                    continue  # the HTTP request went away
                if error is None:
                    waiter.set_result(None)
                else:
                    waiter.set_exception(error)
