from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest

from wakeup_light.light import LightCaps
from wakeup_light.ramp import Curve, kelvin_range, kelvin_to_mired, plan_ticks, step_seconds
from wakeup_light.settings import RampSettings

START = datetime(2026, 10, 12, 3, 30, tzinfo=UTC)


def test_curve_endpoints_and_floor():
    curve = Curve()
    assert curve.level(0) == 2  # level 1 would switch the FLOALT off
    assert curve.level(1) == 254
    assert curve.mired(0) == 454
    assert curve.mired(1) == 250


def test_curve_is_monotonic_and_never_level_one():
    curve = Curve()
    levels = [curve.level(i / 1000) for i in range(1001)]
    assert levels == sorted(levels)
    assert min(levels) == 2


def test_gamma_keeps_the_start_dim():
    assert Curve(gamma=2.5).level(0.5) < Curve(gamma=1).level(0.5)
    assert Curve(gamma=2.5).level(0.25) <= 10  # a quarter in, still a glow


@pytest.mark.parametrize("level", [2, 3, 10, 65, 144, 254])
def test_progress_for_level_inverts_level(level):
    curve = Curve()
    assert abs(curve.level(curve.progress_for_level(level)) - level) <= 1


def test_from_settings_clamps_to_light_range():
    ramp = RampSettings(warm_kelvin=1800, cool_kelvin=6500)
    curve = Curve.from_settings(ramp, LightCaps(min_mireds=250, max_mireds=454))
    assert (curve.warm_mired, curve.cool_mired) == (454, 250)
    assert kelvin_to_mired(2200) == 455 and kelvin_to_mired(4000) == 250


def test_kelvin_slider_range_reaches_both_ends_in_whole_steps():
    # FLOALT: 454..250 mired = 2203..4000 K; 2203 + n*50 would stop at 3953 K.
    low, high = kelvin_range(LightCaps(min_mireds=250, max_mireds=454))
    assert (low, high) == (2200, 4000)
    assert (high - low) % 50 == 0
    assert kelvin_range(LightCaps(min_mireds=153, max_mireds=500)) == (2000, 6550)


def test_step_size():
    assert step_seconds(30 * 60) == 30
    assert step_seconds(120 * 60) == 30
    assert step_seconds(2 * 60) == 2
    assert step_seconds(30) == 2


def test_thirty_minute_plan():
    end = START + timedelta(minutes=30)
    ticks = plan_ticks(START, end, Curve())
    assert len(ticks) == 60
    assert ticks[0].at == START
    assert all(b.at - a.at == timedelta(seconds=30) for a, b in pairwise(ticks))
    assert all(t.transition_s == 28 for t in ticks)  # ends 2 s before the next tick
    assert ticks[0].mireds == 454 and ticks[-1].level == 254
    assert [t.level for t in ticks] == sorted(t.level for t in ticks)
    assert [t.mireds for t in ticks] == sorted((t.mireds for t in ticks), reverse=True)


def test_plan_from_the_middle_keeps_the_original_curve():
    end = START + timedelta(minutes=30)
    curve = Curve()
    now = START + timedelta(minutes=15)
    ticks = plan_ticks(START, end, curve, now=now)
    assert len(ticks) == 30
    assert ticks[0].at == now
    assert ticks[0].mireds == curve.mired(0.5)
    assert ticks[-1].level == 254


def test_short_test_ramp_and_finished_ramp():
    end = START + timedelta(minutes=2)
    ticks = plan_ticks(START, end, Curve())
    assert len(ticks) == 60
    assert ticks[0].transition_s == 1.5
    assert plan_ticks(START, end, Curve(), now=end) == []
