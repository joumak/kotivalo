"""Starts (or resumes) the sunrise for whichever alarm window we are in."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import timedelta

from kotivalo.clock import Clock
from kotivalo.schedule import active_occurrence, occurrences
from kotivalo.settings import Settings, State
from kotivalo.sunrise import Run, SunriseManager

LOGGER = logging.getLogger(__name__)

CHECK_INTERVAL_S = 15


def finished_key(state: State) -> str | None:
    """Key of the last alarm that ran to an end (anything but a process restart)."""
    last = state.last_run or {}
    if last.get("kind") == "alarm" and last.get("result") != "interrupted":
        return last.get("key")
    return None


def prune_skipped(state: State, now) -> bool:
    """Forget skips for alarms more than a day old. Returns True if anything changed."""
    cutoff = (now - timedelta(days=1)).isoformat()
    kept = [key for key in state.skipped if key >= cutoff]
    changed = kept != state.skipped
    state.skipped = kept
    return changed


class AlarmScheduler:
    def __init__(
        self,
        manager: SunriseManager,
        clock: Clock,
        settings: Callable[[], Settings],
        state: Callable[[], State],
        on_start: Callable[[Run], None] | None = None,
    ):
        self.manager = manager
        self.clock = clock
        self.settings = settings
        self.state = state
        self.on_start = on_start
        self._wakeup = asyncio.Event()

    def poke(self) -> None:
        """Re-check right away (settings changed, a sunrise ended, ...)."""
        self._wakeup.set()

    def check(self) -> Run | None:
        """Start the sunrise for the active alarm window if it is not running yet."""
        if self.manager.active is not None:
            return None  # an alarm or test sunrise is already running
        settings, state = self.settings(), self.state()
        if settings.wakeup.light is None or not self.manager.controller.available:
            return None  # no wake-up lamp chosen
        now = self.clock.now()
        occs = occurrences(now, settings.wakeup.alarms, settings.wakeup.ramp, settings.tz)
        occ = active_occurrence(now, occs, skipped=state.skipped)
        if occ is None or occ.key == finished_key(state):
            return None
        run = Run(
            kind="alarm",
            start=occ.start,
            end=occ.alarm,
            off=occ.off,
            key=occ.key,
            light=settings.wakeup.light,
        )
        late = now > occ.start + timedelta(seconds=CHECK_INTERVAL_S * 2)
        verb = "resuming" if late else "starting"
        LOGGER.info("Alarm %s: %s sunrise", occ.label(settings.tz), verb)
        self.manager.start(run)
        if self.on_start is not None:
            self.on_start(run)
        return run

    async def run_forever(self) -> None:
        while True:
            try:
                self.check()
            except Exception:
                LOGGER.exception("Scheduler check failed")
            self._wakeup.clear()
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(CHECK_INTERVAL_S):
                    await self._wakeup.wait()
