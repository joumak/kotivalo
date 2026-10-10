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
OFF_FADE_S = 0.8  # a switch-off first fades down this long
FADE_SETTLE_S = 0.15  # after a fade, before the next command (which would cut it short)
WARM_TO_OFF_S = 0.05  # the lamp has acked the warmth: off right after, so the step hardly shows


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
        """Abort any running transition or move."""

    async def fade(self, level: int, transition_s: float) -> None:
        """Move a lit lamp to `level` over `transition_s`. Never switches a lamp on or off
        (an off FLOALT ignores it)."""

    async def move(self, up: bool, rate: int) -> None:
        """Dim up or down at `rate` levels per second until stop() (a held remote button)."""

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

    async def fade(self, level: int, transition_s: float) -> None:
        self._record("fade", level, transition_s)
        if self.state.on:
            self.state.level = level

    async def move(self, up: bool, rate: int) -> None:
        self._record("move", up, rate)
        # No time passes in a fake: a move goes all the way.
        self.state.on = True if up else self.state.on
        self.state.level = MAX_LEVEL if up else MIN_LEVEL

    async def read_state(self) -> LightState:
        if self.fail:
            raise LightError("fake failure")
        return LightState(**asdict(self.state))

    async def read_caps(self) -> LightCaps:
        if self.fail:
            raise LightError("fake failure")
        return self.caps

    def commands(self) -> list[tuple]:
        """Calls without timestamps, for assertions."""
        return [call[1:] for call in self.calls]


ECHO_GUARD_S = 5  # reports this soon after our own command may predate it


class LightController:
    """Serialises commands to one light and tracks its state.

    The state is what we last commanded, corrected by the lamp's own reports and
    by polling. The lock keeps a CT-then-level pair from interleaving with another
    command.
    """

    def __init__(self, light: Light | None, caps: LightCaps | None = None):
        self.light = light
        self.caps = caps or LightCaps()
        self.state = LightState()
        self.lock = asyncio.Lock()
        self.last_error: str | None = None
        self.reachable: bool | None = None  # None until we have talked to it
        self.failures = 0  # consecutive failed commands or polls
        self.last_command = -1e9  # time.monotonic() of our last command
        self.last_report: float | None = None  # unix time of the lamp's last report

    @property
    def available(self) -> bool:
        return self.light is not None

    def _require(self) -> Light:
        if self.light is None:
            raise LightError("No light selected. Pair one and choose it in the device list.")
        return self.light

    async def _run(self, coro_factory, *, command: bool = True):
        if command:
            self.last_command = time.monotonic()
        try:
            result = await coro_factory()
        except LightError as exc:
            self.last_error = str(exc)
            self.failures += 1
            self.reachable = False
            raise
        self.last_error = None
        self.failures = 0
        self.reachable = True
        return result

    def recently_commanded(self, now: float | None = None) -> bool:
        """True right after our own command, when reports and reads may predate it."""
        return (now if now is not None else time.monotonic()) - self.last_command < ECHO_GUARD_S

    def apply_report(self, attribute: str, value) -> bool:
        """The lamp reported an attribute. Returns True if the state changed.

        Ignored right after our own command: a report sent before the command took
        effect would undo what we just did (the echo guard)."""
        self.last_report = time.time()
        if self.recently_commanded():
            return False
        before = (self.state.on, self.state.level, self.state.mireds)
        if attribute == "on_off":
            self.state.on = bool(value)
        elif attribute == "current_level" and value is not None:
            self.state.level = int(value)
        elif attribute == "color_temperature" and value is not None:
            self.state.mireds = int(value)
        self.reachable, self.failures, self.last_error = True, 0, None
        return before != (self.state.on, self.state.level, self.state.mireds)

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

    def switching_off(self) -> bool:
        """Count the lamp as off from now, while a fade-out runs in the background (views
        update at once). Returns whether it was lit: pass it on to off()."""
        lit = self.state.on is not False
        self.state.on = False
        return lit

    async def off(
        self,
        park_mireds: int | None = None,
        park_level: int | None = None,
        fade_s: float = 0.0,
        lit: bool | None = None,
    ) -> None:
        """Switch off, first 'parking' the lamp so its next switch-on starts there, and
        a sunrise or night light never starts with a flash of the old setting:
        1. fade down to park_level over fade_s;
        2. set the warmth park_mireds at that dim level, where the change hardly shows
           (warmth can't fade: a CT transition freezes a FLOALT);
        3. off, with no transition (IKEA can stay on after a transitioned off)."""
        light = self._require()
        before = self.state.on
        if lit is None:
            lit = before is not False
        self.state.on = False  # what we're doing; the fade doesn't change it
        try:
            if lit and park_level is not None:
                level = max(MIN_LEVEL, min(MAX_LEVEL, park_level))
                await self._run(lambda: light.fade(level, fade_s))
                self.state.level = level
                await asyncio.sleep(fade_s + FADE_SETTLE_S)
            if lit and park_mireds is not None and self.caps.supports_ct:
                mireds = self.caps.clamp_mireds(park_mireds)
                await self._run(lambda: light.set_ct(mireds))
                self.state.mireds = mireds
                await asyncio.sleep(WARM_TO_OFF_S)
            await self._run(light.off)
        except LightError:
            self.state.on = None if lit else before  # lit or not: the next poll tells
            raise

    async def stop(self) -> None:
        light = self._require()
        await self._run(light.stop)

    async def move(self, up: bool, rate: int) -> None:
        """Start dimming; the state is unknown until stop() and a refresh()."""
        light = self._require()
        await self._run(lambda: light.move(up, rate))
        if up:
            self.state.on = True

    async def refresh(self) -> LightState:
        """Read the lamp's actual state (counts toward reachability, not as a command)."""
        light = self._require()
        state = await self._run(light.read_state, command=False)
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
