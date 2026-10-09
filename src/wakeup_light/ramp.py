"""Pure sunrise maths: brightness curve, colour temperature and the tick plan.

Each tick sets colour temperature instantly, then starts one level transition that
ends shortly before the next tick. IKEA lights run one transition at a time and
freeze on CT transitions, so CT never transitions and never overlaps a level change.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from wakeup_light.light import MAX_LEVEL, MIN_LEVEL, LightCaps

MAX_STEP_S = 30.0
MIN_STEP_S = 2.0
MAX_GAP_S = 2.0
KELVIN_STEP = 50  # warmth slider step in the UI


def kelvin_to_mired(kelvin: float) -> int:
    return round(1_000_000 / kelvin)


def mired_to_kelvin(mireds: float) -> int:
    return round(1_000_000 / mireds)


def kelvin_range(caps: LightCaps, step: int = KELVIN_STEP) -> tuple[int, int]:
    """The light's kelvin range widened to whole steps, for a range slider.

    A slider only accepts min + n*step: with the FLOALT's 2203 K warm end and 50 K
    steps the top would be 3953 K instead of 4000 K. Values outside the light's
    range are clamped to it when sent.
    """
    low = mired_to_kelvin(caps.max_mireds) // step * step
    high = -(-mired_to_kelvin(caps.min_mireds) // step) * step
    return low, high


def _clamp01(p: float) -> float:
    return max(0.0, min(1.0, p))


@dataclass(frozen=True)
class Curve:
    gamma: float = 2.5
    warm_mired: int = 454
    cool_mired: int = 250

    @classmethod
    def from_settings(cls, ramp, caps: LightCaps | None) -> Curve:
        warm, cool = kelvin_to_mired(ramp.warm_kelvin), kelvin_to_mired(ramp.cool_kelvin)
        if caps is not None:
            warm, cool = caps.clamp_mireds(warm), caps.clamp_mireds(cool)
        return cls(gamma=ramp.gamma, warm_mired=warm, cool_mired=cool)

    def level(self, p: float) -> int:
        """Brightness for progress p: slow at first (p^gamma), never below MIN_LEVEL."""
        return round(MIN_LEVEL + (MAX_LEVEL - MIN_LEVEL) * _clamp01(p) ** self.gamma)

    def mired(self, p: float) -> int:
        return round(self.warm_mired + (self.cool_mired - self.warm_mired) * _clamp01(p))

    def progress_for_level(self, level: int) -> float:
        """Inverse of level(): where on the ramp a light at this level already is."""
        frac = (level - MIN_LEVEL) / (MAX_LEVEL - MIN_LEVEL)
        return _clamp01(_clamp01(frac) ** (1 / self.gamma))


@dataclass(frozen=True)
class Tick:
    at: datetime
    mireds: int  # set instantly at the start of the tick
    level: int  # reached at the end of the transition
    transition_s: float


def step_seconds(duration_s: float) -> float:
    """About 60 steps per ramp, but never more often than every 2 s or less than every 30 s."""
    return max(MIN_STEP_S, min(MAX_STEP_S, duration_s / 60))


def progress(start: datetime, end: datetime, at: datetime) -> float:
    total = (end - start).total_seconds()
    return 1.0 if total <= 0 else _clamp01((at - start).total_seconds() / total)


def plan_ticks(
    start: datetime, end: datetime, curve: Curve, now: datetime | None = None
) -> list[Tick]:
    """Ticks from max(now, start) to end, with progress measured over the whole ramp."""
    begin = max(now or start, start)
    remaining = (end - begin).total_seconds()
    if remaining <= 0:
        return []
    step = step_seconds((end - start).total_seconds())
    count = max(1, math.ceil(remaining / step - 1e-9))
    dt = remaining / count
    gap = min(MAX_GAP_S, dt / 4)
    ticks = []
    for k in range(count):
        at = begin + timedelta(seconds=k * dt)
        nxt = begin + timedelta(seconds=(k + 1) * dt)
        ticks.append(
            Tick(
                at=at,
                mireds=curve.mired(progress(start, end, at)),
                level=curve.level(progress(start, end, nxt)),
                transition_s=round(dt - gap, 1),
            )
        )
    return ticks
