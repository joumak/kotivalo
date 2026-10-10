from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from kotivalo.clock import FakeClock
from kotivalo.light import FakeLight, LightController
from kotivalo.ramp import Curve
from kotivalo.scheduler import AlarmScheduler, prune_skipped
from kotivalo.settings import Alarm, Settings, State
from kotivalo.sunrise import SunriseManager

TZ = ZoneInfo("Europe/Helsinki")
MONDAY_7 = datetime(2026, 10, 12, 7, 0, tzinfo=TZ).astimezone(UTC)


def make(now: datetime, state: State | None = None):
    settings = Settings()
    settings.alarms[0] = Alarm(enabled=True, time="07:00")
    state = state or State()
    clock = FakeClock(now)
    manager = SunriseManager(LightController(FakeLight(clock=clock)), clock, Curve)
    return AlarmScheduler(manager, clock, lambda: settings, lambda: state), manager


async def test_starts_alarm_in_its_window_once():
    scheduler, manager = make(MONDAY_7 - timedelta(minutes=29))
    run = scheduler.check()
    assert run is not None and run.key == MONDAY_7.isoformat()
    assert scheduler.check() is None  # already running
    await manager.shutdown()


async def test_nothing_outside_the_window():
    scheduler, _ = make(MONDAY_7 - timedelta(minutes=31))
    assert scheduler.check() is None


async def test_finished_alarm_is_not_rerun_but_interrupted_one_resumes():
    key = MONDAY_7.isoformat()
    done = State(last_run={"kind": "alarm", "key": key, "result": "cancelled: manual"})
    scheduler, _ = make(MONDAY_7 - timedelta(minutes=10), done)
    assert scheduler.check() is None

    interrupted = State(last_run={"kind": "alarm", "key": key, "result": "interrupted"})
    scheduler, manager = make(MONDAY_7 - timedelta(minutes=10), interrupted)
    assert scheduler.check() is not None
    await manager.shutdown()


async def test_skipped_alarm_does_not_start():
    state = State(skipped=[MONDAY_7.isoformat()])
    scheduler, _ = make(MONDAY_7 - timedelta(minutes=10), state)
    assert scheduler.check() is None


def test_prune_skipped_forgets_old_keys():
    state = State(skipped=[MONDAY_7.isoformat(), (MONDAY_7 + timedelta(days=7)).isoformat()])
    assert prune_skipped(state, MONDAY_7 + timedelta(days=2))
    assert state.skipped == [(MONDAY_7 + timedelta(days=7)).isoformat()]
