"""Runs one sunrise: ramp up to the alarm time, hold, then switch off."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from wakeup_light.clock import Clock
from wakeup_light.light import MAX_LEVEL, LightController, LightError
from wakeup_light.ramp import Curve, plan_ticks, progress

LOGGER = logging.getLogger(__name__)

CT_TO_LEVEL_DELAY_S = 0.3  # let the instant CT change land before the level transition
ON_TO_CT_DELAY_S = 0.5  # CT is ignored by IKEA while the light is still off


@dataclass
class Run:
    kind: str  # "alarm" or "test"
    start: datetime
    end: datetime  # full brightness (the alarm time)
    off: datetime | None  # auto-off, None = leave on
    key: str | None = None  # alarm occurrence key
    phase: str = "starting"  # ramp, hold, done
    failures: int = 0

    def status(self, now: datetime) -> dict:
        return {
            "kind": self.kind,
            "key": self.key,
            "phase": self.phase,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "off": self.off.isoformat() if self.off else None,
            "progress": round(progress(self.start, self.end, now), 3),
            "failures": self.failures,
        }


class SunriseManager:
    """Owns at most one running sunrise task."""

    def __init__(
        self,
        controller: LightController,
        clock: Clock,
        curve: Callable[[], Curve],
        on_finished: Callable[[Run, str], Awaitable[None] | None] | None = None,
    ):
        self.controller = controller
        self.clock = clock
        self.curve = curve
        self.on_finished = on_finished
        self.run: Run | None = None
        self._task: asyncio.Task | None = None
        self._cancel_reason: str | None = None

    @property
    def active(self) -> Run | None:
        return self.run if self._task is not None and not self._task.done() else None

    def start(self, run: Run) -> None:
        if self.active is not None:
            raise RuntimeError("A sunrise is already running")
        self.run = run
        self._cancel_reason = None
        self._task = asyncio.create_task(self._execute(run), name=f"sunrise-{run.kind}")

    async def wait(self) -> None:
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def cancel(self, reason: str) -> Run | None:
        """Stop the running sunrise (user action). Returns the run that was stopped."""
        run = self.active
        if run is None:
            return None
        was_ramping = run.phase in ("starting", "ramp")
        self._cancel_reason = reason
        self._task.cancel()
        await self.wait()
        if was_ramping:
            with contextlib.suppress(LightError):
                await self.controller.stop()  # end the running transition (and IKEA freezes)
        return run

    async def shutdown(self) -> None:
        """Process exit: stop the task without touching the light or recording a result."""
        if self.active is not None:
            self._task.cancel()
            await self.wait()

    async def _execute(self, run: Run) -> None:
        result = "completed"
        try:
            if self.clock.now() < run.end:
                run.phase = "ramp"
                await self._ramp(run)
            run.phase = "hold"
            if run.off is not None:
                await self.clock.sleep_until(run.off)
                await self._send("off", lambda: self.controller.off(self.curve().warm_mired))
        except asyncio.CancelledError:
            result = f"cancelled: {self._cancel_reason}" if self._cancel_reason else "interrupted"
            raise
        except Exception as exc:
            LOGGER.exception("Sunrise failed")
            result = f"failed: {exc}"
        finally:
            run.phase = "done"
            LOGGER.info("Sunrise %s %s: %s", run.kind, run.key or "", result)
            if self.on_finished is not None:
                outcome = self.on_finished(run, result)
                if asyncio.iscoroutine(outcome):
                    await asyncio.shield(outcome)

    async def _ramp(self, run: Run) -> None:
        curve = self.curve()
        await self.clock.sleep_until(run.start)

        # Never dim a light that is already brighter than the ramp's current point.
        floor = 0
        with contextlib.suppress(LightError):
            state = await self.controller.refresh()
            if state.on and state.level:
                floor = state.level

        now = self.clock.now()
        p = progress(run.start, run.end, now)
        LOGGER.info("Sunrise %s from %.0f%% (light floor level %d)", run.kind, p * 100, floor)
        await self._send(
            "start level", lambda: self.controller.set_level(max(curve.level(p), floor))
        )
        await self.clock.sleep(ON_TO_CT_DELAY_S)
        await self._send("start ct", lambda: self.controller.set_ct(curve.mired(p)))
        await self.clock.sleep(CT_TO_LEVEL_DELAY_S)

        for tick in plan_ticks(run.start, run.end, curve, now=self.clock.now()):
            await self.clock.sleep_until(tick.at)
            await self._send("ct", lambda t=tick: self.controller.set_ct(t.mireds))
            if tick.level > floor:
                await self.clock.sleep(CT_TO_LEVEL_DELAY_S)
                await self._send(
                    "level", lambda t=tick: self.controller.set_level(t.level, t.transition_s)
                )

        # Alarm time: make sure we really are at full brightness, whatever got lost.
        await self.clock.sleep_until(run.end)
        await self._send("final ct", lambda: self.controller.set_ct(curve.mired(1)))
        await self.clock.sleep(CT_TO_LEVEL_DELAY_S)
        await self._send("final level", lambda: self.controller.set_level(MAX_LEVEL))

    async def _send(self, what: str, command: Callable[[], Awaitable[None]]) -> None:
        """Send one command; a lost command is logged and the next tick corrects it."""
        try:
            async with self.controller.lock:
                await command()
        except LightError as exc:
            if self.run is not None:
                self.run.failures += 1
            LOGGER.warning("Sunrise %s not delivered: %s", what, exc)
