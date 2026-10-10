import asyncio
from datetime import UTC, datetime, timedelta

from kotivalo.clock import FakeClock
from kotivalo.light import FakeLight, LightCaps, LightController, LightState
from kotivalo.ramp import Curve
from kotivalo.sunrise import Run, SunriseManager

START = datetime(2026, 10, 12, 3, 30, tzinfo=UTC)
ALARM = START + timedelta(minutes=30)
OFF = ALARM + timedelta(minutes=60)


def setup(now=START, state=None):
    clock = FakeClock(now)
    light = FakeLight(clock=clock)
    if state is not None:
        light.state = state
    controller = LightController(light, LightCaps(supports_ct=True))
    results = []
    manager = SunriseManager(
        controller, clock, Curve, on_finished=lambda run, result: results.append(result)
    )
    return clock, light, manager, results


async def run_to_end(manager, run):
    manager.start(run)
    await manager.wait()


def alarm_run():
    return Run(kind="alarm", start=START, end=ALARM, off=OFF, key=ALARM.isoformat())


async def test_full_sunrise_command_sequence():
    clock, light, manager, results = setup()
    await run_to_end(manager, alarm_run())
    cmds = light.commands()

    assert cmds[:2] == [("level", 2, 0), ("ct", 454)]  # on at the dimmest, then warm
    # full at the alarm; then a fade-out to dim and warm before off, so tomorrow starts dark
    assert cmds[-5:] == [("ct", 250), ("level", 254, 0), ("fade", 2, 1.2), ("ct", 454), ("off",)]
    levels = [c[1] for c in cmds if c[0] == "level"]
    assert min(levels) >= 2
    assert results == ["completed"]
    assert clock.now() == OFF


async def test_ct_never_overlaps_a_level_transition():
    clock, light, manager, _ = setup()
    await run_to_end(manager, alarm_run())
    calls = light.calls
    for i, (t, kind, *args) in enumerate(calls):
        if kind == "level" and args[1] > 0:
            ends = t + timedelta(seconds=args[1])
            next_ct = next((c[0] for c in calls[i + 1 :] if c[1] == "ct"), None)
            assert next_ct is None or next_ct >= ends


async def test_cancel_stops_the_transition_and_sends_nothing_after():
    clock, light, manager, results = setup()
    manager.start(alarm_run())
    for _ in range(50):
        await asyncio.sleep(0)
    run = await manager.cancel("manual")
    assert run is not None and run.phase == "done"
    assert light.commands()[-1] == ("stop",)
    count = len(light.calls)
    await asyncio.sleep(0)
    assert len(light.calls) == count
    assert results == ["cancelled: manual"]
    assert manager.active is None


async def test_shutdown_is_recorded_as_interrupted_and_leaves_light_alone():
    clock, light, manager, results = setup()
    manager.start(alarm_run())
    for _ in range(10):
        await asyncio.sleep(0)
    await manager.shutdown()
    assert ("stop",) not in light.commands()
    assert results == ["interrupted"]


async def test_resume_mid_ramp_starts_at_current_brightness():
    curve = Curve()
    clock, light, manager, _ = setup(now=START + timedelta(minutes=15))
    await run_to_end(manager, alarm_run())
    cmds = light.commands()
    assert cmds[0] == ("level", curve.level(0.5), 0)
    assert cmds[1] == ("ct", curve.mired(0.5))
    assert sum(1 for c in cmds if c[0] == "level" and c[2] > 0) == 30


async def test_never_dims_a_light_that_is_already_bright():
    clock, light, manager, _ = setup(state=LightState(on=True, level=200, mireds=300))
    await run_to_end(manager, alarm_run())
    ramp = [c[1] for c in light.commands() if c[0] == "level"]
    assert ramp[0] == 200
    assert min(ramp) >= 200
    assert ("fade", 2, 1.2) in light.commands()  # dims only in the fade-out before off


async def test_restart_during_hold_only_switches_off_later():
    clock, light, manager, _ = setup(now=ALARM + timedelta(minutes=10))
    await run_to_end(manager, alarm_run())
    assert light.commands() == [("fade", 2, 1.2), ("ct", 454), ("off",)]
    assert clock.now() == OFF


async def test_lost_commands_do_not_abort_the_sunrise():
    clock, light, manager, results = setup()
    light.fail = True
    run = alarm_run()
    await run_to_end(manager, run)
    assert results == ["completed"]
    assert run.failures > 60


async def test_leave_on_after_alarm():
    clock, light, manager, _ = setup()
    run = Run(kind="test", start=START, end=START + timedelta(minutes=2), off=None)
    await run_to_end(manager, run)
    assert light.commands()[-1] == ("level", 254, 0)
    assert light.state.on is True
