"""The long-running service: radio, lamps, scheduler and web UI in one asyncio process."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import time
from dataclasses import asdict
from datetime import datetime, timedelta

import aiohttp
from aiohttp import web

from kotivalo import systemd
from kotivalo.behaviour import Behaviour, SwitchOff, SwitchOn, night_now
from kotivalo.clock import Clock, ntp_synchronized
from kotivalo.events import Announce, Battery, Button, Event, LightReport, Lux, Motion, Seen
from kotivalo.light import (
    MAX_LEVEL,
    MIN_LEVEL,
    OFF_FADE_S,
    FakeLight,
    LatestWins,
    LightController,
    LightError,
)
from kotivalo.ramp import (
    KELVIN_STEP,
    Curve,
    kelvin_range,
    kelvin_to_mired,
    mired_to_kelvin,
)
from kotivalo.registry import Discovered, Registry
from kotivalo.schedule import occurrences, upcoming
from kotivalo.scheduler import AlarmScheduler, prune_skipped
from kotivalo.settings import (
    FAKE_PREFIX,
    Alarm,
    MotionRule,
    NightWindow,
    Profile,
    RampSettings,
    RemoteBinding,
    SettingsError,
    Store,
    WeatherSettings,
    is_fake,
)
from kotivalo.sunrise import Run, SunriseManager
from kotivalo.weather import Forecast, MetClient, fake_forecast, next_refresh, parse_met

LOGGER = logging.getLogger(__name__)

EXIT_CONFIG = 78
RADIO_CHECK_INTERVAL_S = 60
CLOCK_CHECK_INTERVAL_S = 60
STOP_TIMEOUT_S = 5
TEST_HOLD_S = 30
MAX_TEST_MINUTES = 60
LIVE_TRANSITION_S = 0.3  # short fades keep slider dragging smooth
REFRESH_TIMEOUT_S = 12
TICK_ACTIVE_S = 5  # live-update cadence while a sunrise or pairing runs
TICK_IDLE_S = 30
MAX_NAME_LEN = 40
POLL_TICK_S = 5
POLL_INTERVAL_S = 60
POLL_MAX_S = 600
ANNOUNCE_SETTLE_S = 2
BEHAVIOUR_TICK_S = 15  # re-check owner timers at least this often
MOTION_ON_CT_DELAY_S = 0.5  # IKEA ignores colour changes until the lamp is on
DIM_RATE = 85  # levels per second while a remote's button is held: ~3 s end to end
STEP_LEVELS = 51  # one tap of a remote's up/down: 20 %
WARMTH_STEP_MIREDS = 40  # one arrow tap
WARMTH_REPEAT_S = 0.4  # while an arrow is held
HOLD_LIMIT_S = 10  # a held arrow whose release never arrived stops by itself
WEATHER_RETRY_S = 300  # after a failed weather fetch, doubling up to WEATHER_RETRY_MAX_S
WEATHER_RETRY_MAX_S = 1800
WEATHER_STALE_S = 3 * 3600  # older weather is not shown
CONFIGURE_RETRY_S = 300  # a sleepy device that failed setup is retried at most this often


def poll_delay(failures: int) -> float:
    """Seconds until the next poll: every minute, backing off to 10 min while a lamp
    does not answer (each poll of a missing lamp costs route discovery on the XBee)."""
    return float(min(POLL_MAX_S, POLL_INTERVAL_S * 2**failures))


def fake_devices(lamps: int, sensors: int = 0, remotes: int = 0) -> list[Discovered]:
    return [
        *(
            Discovered(f"{FAKE_PREFIX}{i:02x}", "light", "Fake panel", "Test", 1)
            for i in range(1, lamps + 1)
        ),
        *(
            Discovered(f"{FAKE_PREFIX}f{i}", "motion", "Fake motion sensor", "Test")
            for i in range(1, sensors + 1)
        ),
        *(
            Discovered(f"{FAKE_PREFIX}e{i}", "remote", "Remote Control N2", "Test")
            for i in range(1, remotes + 1)
        ),
    ]


class Service:
    def __init__(
        self,
        store: Store,
        *,
        fake: bool = False,
        fake_lamps: int = 2,
        fake_sensors: int = 0,
        fake_remotes: int = 0,
        clock: Clock | None = None,
    ):
        self.store = store
        self.fake = fake
        self.fake_lamps = fake_lamps
        self.fake_sensors = fake_sensors
        self.fake_remotes = fake_remotes
        self.clock = clock or Clock()
        self.settings = store.load_settings()
        self.state = store.load_state()
        self.registry = Registry(self.settings, self._make_light)
        self.behaviour = Behaviour(self.settings)
        self.behaviour.load(self.state.behaviour)
        self.manager = SunriseManager(
            LightController(None),
            self.clock,
            self.curve,
            self._finished,
            keep_on=self._keep_on_after_sunrise,
        )
        self.scheduler = AlarmScheduler(
            self.manager,
            self.clock,
            lambda: self.settings,
            lambda: self.state,
            on_start=self._sunrise_started,
        )
        self.zigbee = None  # zigpy ControllerApplication
        self.clock_synced: bool | None = None
        self.pairing_until: datetime | None = None
        self.last_event: str | None = None
        self.last_test: dict | None = None
        self.stopped = asyncio.Event()
        self.exit_code = 0
        self._tasks: list[asyncio.Task] = []
        self._fake_lights: dict[str, FakeLight] = {}
        self._live: dict[str, LatestWins] = {}
        self._changed = asyncio.Event()
        self.events: asyncio.Queue[Event] = asyncio.Queue()
        self._behaviour_changed = asyncio.Event()
        self._configuring: set[str] = set()
        self._configure_tried: dict[str, datetime] = {}
        self.remote_memo: dict[str, dict] = {}  # battery and last press, until a restart
        self._repeats: dict[str, asyncio.Task] = {}  # held arrows, per remote
        self.firmware: dict[str, dict] = {}  # firmware updates: state and progress
        self.weather: Forecast | None = None
        self.weather_fetched: datetime | None = None
        self.fetch_weather = MetClient().fetch  # (lat, lon) -> (json, expires); tests replace it
        self._weather_changed = asyncio.Event()
        self._weather_failures = 0

    # --- lifecycle ---------------------------------------------------------------

    @property
    def controller(self) -> LightController:
        """The wake-up lamp's controller (a light-less one when none is chosen)."""
        return self.manager.controller

    def curve(self) -> Curve:
        return Curve.from_settings(self.settings.wakeup.ramp, self.controller.caps)

    def _make_light(self, ieee: str, endpoint: int | None):
        if self.fake:
            return self._fake_lights.setdefault(ieee, FakeLight(clock=self.clock))
        if self.zigbee is None:
            return None
        from kotivalo.zigbee import ZigbeeLight

        return ZigbeeLight(self.zigbee, ieee, endpoint)

    async def start(self) -> None:
        if self.fake:
            found = fake_devices(self.fake_lamps, self.fake_sensors, self.fake_remotes)
        else:
            from kotivalo.zigbee import DeviceEvents, EventBridge, discover, start_app

            def attach(app) -> None:  # before the radio starts: no report is missed
                bridge = EventBridge(self.events)
                bridge.attach_all(app)
                app.add_listener(bridge)

            self.zigbee = await start_app(
                self.settings.radio, self.store.db_path, on_created=attach
            )
            self.zigbee.add_listener(DeviceEvents(self._device_event))
            found = discover(self.zigbee)
            self._spawn(self._radio_watch())
        if self.registry.sync(found):
            self._save_settings()
        if self.fake and self.settings.wakeup.light is None and found:
            self.settings.wakeup.light = found[0].ieee  # in memory only
        self._attach_wakeup()
        await self._refresh_all()
        self._reconcile_owners()
        self._spawn(self.scheduler.run_forever())
        self._spawn(self._clock_watch())
        self._spawn(self._ticker())
        self._spawn(self._consume_events())
        self._spawn(self._poll_lamps())
        self._spawn(self._behaviour_loop())
        self._spawn(self._weather_loop())
        if self.zigbee is not None:
            self._spawn_logged(self._configure_lamps(), "Configuring lamp reporting")

    async def stop(self) -> None:
        await self.manager.shutdown()
        for remote in list(self._repeats):
            self._stop_repeat(remote)
        for task in self._tasks:
            task.cancel()
        # Bounded: a task that swallows its cancellation must not hang shutdown.
        if self._tasks:
            _, pending = await asyncio.wait(self._tasks, timeout=STOP_TIMEOUT_S)
            for task in pending:
                LOGGER.warning("Background task did not stop: %r", task)
        if self.zigbee is not None:
            await self.zigbee.shutdown()

    def start_watchdog(self) -> None:
        """Ping systemd's watchdog while the event loop runs. If the loop blocks, or the
        process hangs on its way out, systemd kills and restarts it."""
        interval = systemd.watchdog_interval()
        if interval:
            self._spawn(self._watchdog(interval))

    async def _watchdog(self, interval: float) -> None:
        while True:
            systemd.notify("WATCHDOG=1")
            await asyncio.sleep(interval)

    def request_stop(self, exit_code: int = 0) -> None:
        self.exit_code = exit_code
        self.stopped.set()
        self.notify()  # ends the live-update streams

    def _spawn(self, coro) -> None:
        self._tasks.append(asyncio.create_task(coro))

    def _spawn_logged(self, coro, what: str) -> None:
        """Fire-and-forget work whose failure must at least reach the log."""

        async def run():
            try:
                await coro
            except Exception:
                LOGGER.exception("%s failed", what)
            finally:
                self.notify()

        task = asyncio.create_task(run())
        self._tasks.append(task)
        task.add_done_callback(self._tasks.remove)

    def _save_settings(self) -> None:
        self.store.save_settings(self.settings)

    def _attach_wakeup(self) -> None:
        """Point the sunrise at the wake-up lamp. Only while no sunrise is running."""
        ieee = self.settings.wakeup.light
        controller = self.registry.controllers.get(ieee) if ieee else None
        self.manager.controller = controller or LightController(None)

    async def _refresh_all(self) -> None:
        """Read every lamp's capabilities and state (unreachable lamps are skipped)."""

        async def refresh(ieee: str, controller: LightController) -> bool:
            with contextlib.suppress(LightError, TimeoutError):
                async with asyncio.timeout(REFRESH_TIMEOUT_S), controller.lock:
                    caps = await controller.light.read_caps()
                    changed = caps != controller.caps
                    self.registry.set_caps(ieee, caps)
                    await controller.refresh()
                    return changed
            return False

        lamps = [(i, c) for i, c in self.registry.controllers.items() if c.available]
        if any(await asyncio.gather(*(refresh(i, c) for i, c in lamps))):
            self._save_settings()

    async def _radio_watch(self) -> None:
        """zigpy has no XBee watchdog: poll the radio and exit (systemd restarts us) if it hangs."""
        api = getattr(self.zigbee, "_api", None)
        if api is None or not hasattr(api, "_at_command"):
            return
        failures = 0
        while True:
            await asyncio.sleep(RADIO_CHECK_INTERVAL_S)
            try:
                async with asyncio.timeout(5):
                    await api._at_command("AI")
                failures = 0
            except Exception as exc:  # noqa: BLE001
                failures += 1
                LOGGER.warning("Radio check failed (%d): %r", failures, exc)
                if failures >= 2:
                    LOGGER.error("Radio not responding, exiting for a restart")
                    self.request_stop(1)
                    return

    async def _clock_watch(self) -> None:
        while True:
            synced = True if self.fake else await ntp_synchronized()
            if synced != self.clock_synced:
                self.clock_synced = synced
                self.notify()
            if prune_skipped(self.state, self.clock.now()):
                self.store.save_state(self.state)
            await asyncio.sleep(CLOCK_CHECK_INTERVAL_S)

    async def _ticker(self) -> None:
        """Periodic live updates: sunrise progress, pairing countdown, relative times."""
        idle = 0.0
        while True:
            await asyncio.sleep(TICK_ACTIVE_S)
            idle += TICK_ACTIVE_S
            if self.manager.active is not None or self._pairing_open() or idle >= TICK_IDLE_S:
                idle = 0.0
                self.notify()

    def _device_event(self, kind: str, obj) -> None:
        if kind == "connection_lost":
            if obj is not None:
                LOGGER.error("Radio connection lost: %r", obj)
                self.request_stop(1)
            return
        name = f"{obj.manufacturer or ''} {obj.model or ''}".strip() or str(obj.ieee)
        self.last_event = f"{kind}: {name} ({obj.ieee})"
        LOGGER.info("Device %s", self.last_event)
        if kind in ("joined", "initialized"):
            from kotivalo.zigbee import discovered

            ieee = str(obj.ieee)
            known_lamp = ieee in self.registry.controllers
            if self.registry.sync([discovered(obj)]):
                self._save_settings()
            # A re-paired lamp already in the database is not re-interviewed: set it up
            # again on "joined" too.
            if ieee in self.registry.controllers and (kind == "initialized" or known_lamp):
                self._spawn_logged(self._setup_lamp(ieee), f"Setting up lamp {ieee}")
            elif self._sleepy(ieee):
                self.settings.devices[ieee].configured = False  # a (re)joined sensor or remote
                self._configure_soon(ieee)  # it is awake right now
        self.notify()

    async def _setup_lamp(self, ieee: str) -> None:
        """A lamp joined: read its capabilities, set its power-on behaviour, adopt it as
        the wake-up lamp if there is none, and ask it for reports."""
        controller = self.registry.controller(ieee)
        caps = await controller.light.read_caps()
        self.registry.set_caps(ieee, caps)
        if self.settings.wakeup.light is None:
            await self.set_wakeup_light(ieee)
        else:
            await self._apply_power_on(ieee)
        self.settings.devices[ieee].configured = False  # a (re)joined lamp lost its bindings
        self._save_settings()
        await self._configure_lamp(ieee)
        with contextlib.suppress(LightError):
            async with controller.lock:
                await controller.refresh()

    async def _configure_lamps(self) -> None:
        """Ask every lamp not yet set up for reports. Lamps are routers, always awake."""
        for ieee in self.registry.light_ieees():
            if not self.settings.devices[ieee].configured:
                await self._configure_lamp(ieee)

    async def _configure_lamp(self, ieee: str) -> None:
        import zigpy.types

        from kotivalo.zigbee import configure_lamp

        if self.zigbee is None:
            return
        try:
            device = self.zigbee.get_device(ieee=zigpy.types.EUI64.convert(ieee))
        except KeyError:
            return
        if await configure_lamp(device, self.settings.devices[ieee].endpoint):
            self.settings.devices[ieee].configured = True
            self._save_settings()

    def _sleepy(self, ieee: str) -> bool:
        """A battery device (motion sensor or remote): configured only while awake."""
        device = self.settings.devices.get(ieee)
        return device is not None and device.kind in ("motion", "remote")

    def _configure_soon(self, ieee: str, retry: bool = False) -> None:
        """Configure a sleepy device while it is awake (it just joined or sent something).
        A retry waits a while after a failed attempt: each one queues requests that wait
        30 s for an answer, and a flaky device would keep the XStick busy."""
        if ieee in self._configuring or self.zigbee is None:
            return
        now = self.clock.now()
        tried = self._configure_tried.get(ieee)
        if retry and tried is not None and (now - tried).total_seconds() < CONFIGURE_RETRY_S:
            return
        self._configure_tried[ieee] = now
        self._configuring.add(ieee)

        async def run():
            import zigpy.types

            from kotivalo.zigbee import configure_remote, configure_sensor

            remote = self.settings.devices[ieee].kind == "remote"
            configure = configure_remote if remote else configure_sensor
            try:
                device = self.zigbee.get_device(ieee=zigpy.types.EUI64.convert(ieee))
                if await configure(device):
                    self.settings.devices[ieee].configured = True
                    self._save_settings()
            finally:
                self._configuring.discard(ieee)

        self._spawn_logged(run(), f"Configuring {ieee}")

    async def _consume_events(self) -> None:
        """Every device event, in one place."""
        while True:
            event = await self.events.get()
            try:
                self._handle_event(event)
            except Exception:
                LOGGER.exception("Handling %r failed", event)

    def _handle_event(self, event: Event) -> None:
        now = self.clock.now()
        controller = self.registry.controllers.get(event.ieee)
        match event:
            case LightReport(attribute=attribute, value=value) if controller is not None:
                was_on = controller.state.on
                if controller.apply_report(attribute, value):
                    self._lamp_seen(event.ieee, was_on)
                    self.notify()
            case Announce() if controller is not None:
                # Typically a lamp that just got mains power back (a wall switch).
                LOGGER.info("Lamp %s announced itself; reading its state", event.ieee)
                self._spawn_logged(self._refresh_soon(event.ieee), f"Refreshing {event.ieee}")
            case Motion(occupied=occupied):
                night = self._night(now)
                actions = self.behaviour.motion(event.ieee, occupied, now, night)
                self._log_motion(event.ieee, occupied, actions, now, night)
                self._run_actions(actions)
                self._behaviour_saved()
            case Lux(lux=lux):
                self.behaviour.lux(event.ieee, lux, now)
                self.notify()
            case Battery(percent=percent) if self._kind(event.ieee) == "remote":
                self.remote_memo.setdefault(event.ieee, {})["battery"] = percent
                self.notify()
            case Battery(percent=percent):
                self.behaviour.battery(event.ieee, percent)
                self.notify()
            case Button(action=action):
                self._remote_pressed(event.ieee, action)
            case Seen():
                if self._sleepy(event.ieee) and not self.settings.devices[event.ieee].configured:
                    self._configure_soon(event.ieee, retry=True)

    def _kind(self, ieee: str) -> str | None:
        device = self.settings.devices.get(ieee)
        return device.kind if device else None

    def _log_motion(self, sensor: str, occupied: bool, actions, now: datetime, night: bool) -> None:
        name = self.settings.devices[sensor].name if sensor in self.settings.devices else sensor
        rule = self.behaviour.rule_for_sensor(sensor)
        if not occupied or rule is None:
            LOGGER.info(
                "%s: %s%s", name, "motion" if occupied else "empty", "" if rule else " (no rule)"
            )
            return
        switched = {a.ieee for a in actions}
        for ieee in rule.lights:
            lamp = self.settings.devices.get(ieee)
            label = lamp.name if lamp else ieee
            if ieee in switched:
                LOGGER.info(
                    "%s: motion, switching on %s (%s)", name, label, "night" if night else "day"
                )
            else:
                reason = (
                    self.behaviour.why_not_on(ieee, sensor, now, night) or "already on by motion"
                )
                LOGGER.info("%s: motion, %s left as it is: %s", name, label, reason)

    def _lamp_seen(self, ieee: str, was_on: bool | None) -> None:
        """A report or a poll showed the lamp's real state: let the owner model follow
        changes made outside the service (a wall switch)."""
        on = self.registry.controller(ieee).state.on
        if on is not None and on != was_on:
            self.behaviour.lamp_state(ieee, on, self.clock.now())
            self._behaviour_saved()

    def _reconcile_owners(self) -> None:
        """At startup: owners from state.json against what the lamps actually do."""
        now = self.clock.now()
        for ieee, controller in self.registry.controllers.items():
            if controller.state.on is not None:
                self.behaviour.lamp_state(ieee, controller.state.on, now)
        self._behaviour_saved()

    def _behaviour_saved(self) -> None:
        self.state.behaviour = self.behaviour.to_dict()
        self.store.save_state(self.state)
        self._behaviour_changed.set()
        self.notify()

    def _night(self, now: datetime) -> bool:
        """The night window, ended early by a sunrise that started this morning."""
        wakeup = self.settings.wakeup
        occs = occurrences(now, wakeup.alarms, wakeup.ramp, self.settings.tz)
        started = [
            o.start
            for o in occs
            if o.key not in self.state.skipped and now - timedelta(hours=12) < o.start <= now
        ]
        return night_now(now, self.settings.tz, self.settings.night, max(started, default=None))

    def _run_actions(self, actions) -> None:
        for action in actions:
            match action:
                case SwitchOn(ieee=ieee, level=level, kelvin=kelvin):
                    self._spawn_logged(self._switch_on(ieee, level, kelvin), f"Motion on {ieee}")
                case SwitchOff(ieee=ieee):
                    self._spawn_logged(self._switch_off(ieee), f"Motion off {ieee}")

    async def _switch_on(self, ieee: str, level: int, kelvin: int) -> None:
        controller = self.registry.controller(ieee)
        async with controller.lock:
            await controller.set_level(level, 0)
            await asyncio.sleep(MOTION_ON_CT_DELAY_S)
            await controller.set_ct(kelvin_to_mired(kelvin))

    async def _switch_off(self, ieee: str) -> None:
        controller = self.registry.controller(ieee)
        async with controller.lock:
            await controller.off(**self._park(ieee, controller))

    def _park(self, ieee: str, controller: LightController) -> dict:
        """Off fades out to dim. The wake-up lamp also turns warm, so its next start (a
        sunrise, a night light) never flashes cool; other lamps keep their warmth, as
        "on" restores the last setting by hand anyway."""
        warm = ieee == self.settings.wakeup.light and controller.caps.supports_ct
        return {
            "park_mireds": controller.caps.max_mireds if warm else None,
            "park_level": MIN_LEVEL,
            "fade_s": OFF_FADE_S,
        }

    async def _behaviour_loop(self) -> None:
        """Runs the owner model's timers (motion off, silent sensors)."""
        while True:
            deadline = self.behaviour.next_deadline()
            wait = BEHAVIOUR_TICK_S
            if deadline is not None:
                wait = max(0.0, min(wait, (deadline - self.clock.now()).total_seconds()))
            self._behaviour_changed.clear()
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(wait):
                    await self._behaviour_changed.wait()
            actions = self.behaviour.tick(self.clock.now())
            if actions:
                self._run_actions(actions)
                self._behaviour_saved()

    def _sunrise_started(self, run: Run) -> None:
        if run.light:
            self.behaviour.sunrise_started(run.light)
            self._behaviour_saved()

    def _keep_on_after_sunrise(self, run: Run) -> bool:
        keep = bool(run.light) and self.behaviour.keep_on_after_sunrise(run.light, self.clock.now())
        self._behaviour_saved()
        return keep

    async def _refresh_soon(self, ieee: str) -> None:
        await asyncio.sleep(ANNOUNCE_SETTLE_S)  # give a booting lamp a moment
        with contextlib.suppress(LightError, TimeoutError):
            await self._poll_lamp(self.registry.controller(ieee))

    async def _poll_lamp(self, controller: LightController) -> None:
        try:
            async with asyncio.timeout(REFRESH_TIMEOUT_S), controller.lock:
                await controller.refresh()
        except TimeoutError:
            controller.failures += 1
            controller.reachable = False
            controller.last_error = "no answer"
            raise

    async def _poll_lamps(self) -> None:
        """Read each lamp now and then: catches wall switches and lost reports. A lamp
        that does not answer is polled less often (its power may simply be off)."""
        next_poll: dict[str, float] = {}
        while True:
            await asyncio.sleep(POLL_TICK_S)
            for ieee, controller in list(self.registry.controllers.items()):
                now = time.monotonic()
                if (
                    not controller.available
                    or now < next_poll.get(ieee, 0)
                    or controller.recently_commanded(now)
                    or controller.lock.locked()
                ):
                    continue
                before = (controller.reachable, asdict(controller.state))
                was_on = controller.state.on
                with contextlib.suppress(LightError, TimeoutError):
                    await self._poll_lamp(controller)
                next_poll[ieee] = time.monotonic() + poll_delay(controller.failures)
                if (controller.reachable, asdict(controller.state)) != before:
                    self._lamp_seen(ieee, was_on)
                    self.notify()

    def _set_power_on_policy(self, ieee: str) -> bool:
        """The wake-up lamp keeps its state over a power cut (a night-time cut must not
        wake you); other lamps switch on, so their wall switch works. Settings only;
        returns True for "previous"."""
        light_settings = self.settings.light_settings(ieee)
        light_settings.power_on = "previous" if ieee == self.settings.wakeup.light else "on"
        return light_settings.power_on == "previous"

    async def _apply_power_on(self, ieee: str) -> None:
        """Set the policy in the settings (caller saves) and write it to the lamp."""
        previous = self._set_power_on_policy(ieee)
        light = self.registry.controller(ieee).light
        if hasattr(light, "set_power_on"):
            await light.set_power_on(previous=previous)

    async def _finished(self, run: Run, result: str) -> None:
        if result == "interrupted":
            return  # process shutdown: resume after restart
        if run.light and run.light in self.registry.controllers:
            lamp_on = self.registry.controller(run.light).state.on is True
            self.behaviour.sunrise_ended(run.light, lamp_on, self.clock.now())
            self._behaviour_saved()
        record = {
            "kind": run.kind,
            "key": run.key,
            "light": run.light,
            "result": result,
            "failures": run.failures,
            "finished": self.clock.now().isoformat(),
        }
        if run.kind == "alarm":
            self.state.last_run = record
            self.store.save_state(self.state)
        else:
            self.last_test = record
        self.scheduler.poke()
        self.notify()

    # --- live updates ----------------------------------------------------------------

    def notify(self) -> None:
        """Something changed: wake the live-update streams."""
        self._changed.set()
        self._changed = asyncio.Event()

    async def wait_change(self, max_wait_s: float) -> bool:
        changed = self._changed
        try:
            async with asyncio.timeout(max_wait_s):
                await changed.wait()
        except TimeoutError:
            return False
        return True

    # --- actions (called by the web API) --------------------------------------------

    async def stop_sunrise(self, reason: str) -> None:
        run = await self.manager.cancel(reason)
        if run is not None and run.key and run.key not in self.state.skipped:
            self.state.skipped.append(run.key)  # don't let the scheduler restart it
            self.store.save_state(self.state)

    def _require_wakeup(self) -> str:
        if self.settings.wakeup.light is None:
            raise LightError("No wake-up lamp chosen")
        return self.settings.wakeup.light

    async def lamp_action(self, ieee: str, action: str, value: float | None = None) -> None:
        controller = self.registry.controller(ieee)
        if action == "auto":
            self._let_motion_control(ieee, controller)
            return
        run = self.manager.active
        in_sunrise = run is not None and run.light == ieee
        if ieee == self.settings.wakeup.light:
            await self.stop_sunrise("manual control")
        if action == "toggle":
            action = "off" if controller.state.on else "on"
        if action not in ("on", "off", "level", "kelvin"):
            raise SettingsError(f"Unknown light action {action!r}")
        if action in ("level", "kelvin") and value is None:
            raise SettingsError(f"{action} needs a value")
        # Manual wins: from now on motion leaves this lamp alone (or, after an off,
        # until the room has been empty for a while).
        self.behaviour.manual(ieee, action != "off", self.clock.now())
        self._behaviour_saved()
        if action in ("level", "kelvin"):
            self._remember_manual(ieee, action, int(value))
            await self._live_sender(ieee).submit(action, int(value))
            return
        if action == "off":  # fades out in the background; shown as off at once
            lit = controller.switching_off()
            self._spawn_logged(self._fade_off(ieee, lit), f"Switching off {ieee}")
            return
        async with controller.lock:
            await self._manual_on(ieee, controller, full=in_sunrise)

    async def _fade_off(self, ieee: str, lit: bool) -> None:
        controller = self.registry.controller(ieee)
        async with controller.lock:
            await controller.off(**self._park(ieee, controller), lit=lit)

    async def _manual_on(self, ieee: str, controller: LightController, full: bool) -> None:
        """On at the last level and warmth set by hand (a lamp parked at its minimum would
        otherwise come on there). During a sunrise "on" means "I'm up": full brightness."""
        if full:
            await controller.set_level(MAX_LEVEL, 0)
            return
        last = self.settings.light_settings(ieee).last_manual
        await controller.set_level(last.level, 0)
        if controller.caps.supports_ct:
            await asyncio.sleep(MOTION_ON_CT_DELAY_S)
            await controller.set_ct(kelvin_to_mired(last.kelvin))

    def _let_motion_control(self, ieee: str, controller: LightController) -> None:
        """Hands the lamp back to its motion sensor (a running sunrise is left alone)."""
        if self.behaviour.rule_for_lamp(ieee) is None:
            raise SettingsError("No motion sensor controls this lamp")
        now = self.clock.now()
        actions = self.behaviour.automatic(ieee, bool(controller.state.on), now, self._night(now))
        LOGGER.info("Motion controls %s again (owner %s)", ieee, self.behaviour.lamp(ieee).owner)
        self._behaviour_saved()
        self._run_actions(actions)

    # --- remotes -----------------------------------------------------------------------

    def _remote_lamps(self, remote: str) -> list[str]:
        binding = next((b for b in self.settings.remotes if b.remote == remote), None)
        lights = binding.lights if binding else []
        return [ieee for ieee in lights if ieee in self.registry.controllers]

    def _remote_pressed(self, remote: str, action: str) -> None:
        """A remote's button: every lamp it controls follows (manual wins)."""
        memo = self.remote_memo.setdefault(remote, {})
        memo["last_action"], memo["last_press"] = action, self.clock.now()
        lamps = self._remote_lamps(remote)
        name = self.settings.devices[remote].name if remote in self.settings.devices else remote
        LOGGER.info("Remote %s: %s, lamps %s", name, action, lamps or "none")
        self.notify()
        if action in ("warmer_hold", "cooler_hold", "arrow_stop"):
            self._stop_repeat(remote)
        if not lamps:
            return
        if action == "toggle":
            on = any(self.registry.controller(ieee).state.on for ieee in lamps)
            action = "off" if on else "on"
        if action in ("warmer_hold", "cooler_hold"):
            self._repeats[remote] = asyncio.create_task(
                self._repeat_warmth(lamps, warmer=action == "warmer_hold")
            )
            return
        for ieee in lamps:
            self._spawn_logged(self._remote_action(ieee, action), f"Remote {action} on {ieee}")

    async def _remote_action(self, ieee: str, action: str) -> None:
        controller = self.registry.controller(ieee)
        on = controller.state.on is True
        match action:
            case "on" | "off":
                await self.lamp_action(ieee, action)
            case "brighter" | "dimmer" if on or action == "brighter":
                level = (controller.state.level or MIN_LEVEL) if on else 0
                step = STEP_LEVELS if action == "brighter" else -STEP_LEVELS
                await self.lamp_action(ieee, "level", max(MIN_LEVEL, min(MAX_LEVEL, level + step)))
            case "brighter_hold" | "dimmer_hold" if on or action == "brighter_hold":
                if ieee == self.settings.wakeup.light:
                    await self.stop_sunrise("manual control")
                self.behaviour.manual(ieee, True, self.clock.now())
                self._behaviour_saved()
                async with controller.lock:
                    await controller.move(action == "brighter_hold", DIM_RATE)
            case "dim_stop":
                async with controller.lock:
                    await controller.stop()
                    state = await controller.refresh()
                if state.on and state.level:
                    self._remember_manual(ieee, "level", state.level)
                    self._save_settings()
            case "warmer" | "cooler" if on:
                await self._step_warmth(ieee, warmer=action == "warmer")

    async def _step_warmth(self, ieee: str, warmer: bool) -> None:
        controller = self.registry.controller(ieee)
        if controller.state.on is not True or not controller.caps.supports_ct:
            return
        mireds = controller.state.mireds or controller.caps.min_mireds
        mireds = controller.caps.clamp_mireds(
            mireds + (WARMTH_STEP_MIREDS if warmer else -WARMTH_STEP_MIREDS)
        )
        await self.lamp_action(ieee, "kelvin", mired_to_kelvin(mireds))

    async def _repeat_warmth(self, lamps: list[str], warmer: bool) -> None:
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(HOLD_LIMIT_S):
                while True:
                    for ieee in lamps:
                        try:
                            await self._step_warmth(ieee, warmer)
                        except LightError as exc:
                            LOGGER.warning("Warmth step on %s failed: %s", ieee, exc)
                    self.notify()
                    await asyncio.sleep(WARMTH_REPEAT_S)

    def _stop_repeat(self, remote: str) -> None:
        task = self._repeats.pop(remote, None)
        if task is not None:
            task.cancel()

    def start_firmware_update(self, ieee: str) -> None:
        """Update a remote's firmware from IKEA's server, in the background. Old remotes
        (E1743, E1810 before 2.3.075) send only to groups, which the XStick drops."""
        if self._kind(ieee) != "remote":
            raise SettingsError(f"{ieee} is not a remote")
        if self.zigbee is None or is_fake(ieee):
            raise SettingsError("Firmware updates need the radio")
        if self.firmware.get(ieee, {}).get("state") in ("waiting", "updating"):
            raise SettingsError("A firmware update is already running")
        self.firmware[ieee] = {"state": "waiting", "progress": 0.0}
        self._spawn_logged(self._update_firmware(ieee), f"Firmware update of {ieee}")

    async def _update_firmware(self, ieee: str) -> None:
        import zigpy.types

        from kotivalo.zigbee import find_firmware, update_firmware

        status = self.firmware[ieee]
        reported = -10.0

        def progress(percent: float) -> None:
            nonlocal reported
            status.update(state="updating", progress=round(percent, 1))
            if percent - reported >= 10:
                reported = percent
                LOGGER.info("Firmware update of %s: %.0f %%", ieee, percent)
            self.notify()

        try:
            device = self.zigbee.get_device(ieee=zigpy.types.EUI64.convert(ieee))
            image = await find_firmware(device)
            if image is None:
                status["state"] = "none"
                return
            LOGGER.info("Updating %s to firmware %s", ieee, image.metadata.file_version)
            status["state"] = await update_firmware(device, image, progress)
        except Exception:
            status["state"] = "failed"
            raise
        LOGGER.info("Firmware update of %s: %s", ieee, status["state"])
        if status["state"] == "done":  # unicast bindings work now: set it up when it wakes
            self.settings.devices[ieee].configured = False
            self._save_settings()

    # --- weather -----------------------------------------------------------------------

    async def _weather_loop(self) -> None:
        """Keeps the forecast fresh: when MET says it expires, sooner when the place changes."""
        while True:
            self._weather_changed.clear()
            delay = await self._refresh_weather() if self.settings.weather.enabled else None
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(delay):
                    await self._weather_changed.wait()

    async def _refresh_weather(self) -> float:
        """Fetches the forecast; returns seconds until the next try."""
        place = self.settings.weather
        now = self.clock.now()
        try:
            if self.fake:
                forecast, expires = fake_forecast(now), None
            else:
                data, expires = await self.fetch_weather(place.lat, place.lon)
                forecast = parse_met(data)
                if forecast is None:
                    raise ValueError("no hourly forecast in the response")
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            self._weather_failures += 1
            if self._weather_failures == 1:
                LOGGER.warning("Weather for %s failed: %r", place.name or "home", exc)
            return min(WEATHER_RETRY_MAX_S, WEATHER_RETRY_S * 2 ** (self._weather_failures - 1))
        if self.settings.weather is not place:  # moved while fetching: fetch the new place
            return 0.0
        first = self.weather is None or self._weather_failures > 0
        self._weather_failures = 0
        self.weather, self.weather_fetched = forecast, now
        wait = next_refresh(expires, now)
        log = LOGGER.info if first else LOGGER.debug
        log("Weather for %s updated, next in %d min", place.name or "home", wait // 60)
        self.notify()
        return wait

    def update_weather(self, data: dict) -> None:
        """Set the place to show the weather for; lat/lon null switches the weather off."""
        lat, lon = data.get("lat"), data.get("lon")
        if lat is None or lon is None:
            place = WeatherSettings()
        else:
            try:
                lat, lon = round(float(lat), 2), round(float(lon), 2)
            except (TypeError, ValueError):
                raise SettingsError("Latitude and longitude must be numbers") from None
            place = WeatherSettings(str(data.get("name", "")).strip(), lat, lon)
        previous = self.settings.weather
        self.settings.weather = place
        try:
            self._save_settings()
        except SettingsError:
            self.settings.weather = previous
            raise
        if (place.lat, place.lon) != (previous.lat, previous.lon):
            self.weather, self.weather_fetched, self._weather_failures = None, None, 0
            self._weather_changed.set()

    async def search_places(self, query: str, language: str) -> list[dict]:
        from kotivalo.weather import parse_coordinates, search_places

        if self.fake and parse_coordinates(query) is None:
            places = [("Helsinki", "Uusimaa", 60.17, 24.94), ("Espoo", "Uusimaa", 60.21, 24.66)]
            return [
                {"name": n, "region": r, "country": "Suomi", "lat": lat, "lon": lon}
                for n, r, lat, lon in places
                if query.strip().lower() in n.lower()
            ]
        return await search_places(query, language)

    def weather_status(self) -> dict:
        place = self.settings.weather
        now = self.clock.now()
        fresh = (
            self.weather_fetched is not None
            and (now - self.weather_fetched).total_seconds() < WEATHER_STALE_S
        )
        return {
            "location": (
                {"name": place.name, "lat": place.lat, "lon": place.lon} if place.enabled else None
            ),
            "forecast": self.weather.view(now) if self.weather and place.enabled else None,
            "stale": not fresh,
        }

    def update_remote(self, remote: str, data: dict) -> None:
        """Which lamps a remote controls."""
        if self._kind(remote) != "remote":
            raise SettingsError(f"{remote} is not a remote")
        lights = [str(x) for x in data.get("lights", [])]
        if not_lamps := [ieee for ieee in lights if ieee not in self.registry.controllers]:
            raise SettingsError(f"Not lamps: {', '.join(not_lamps)}")
        others = [b for b in self.settings.remotes if b.remote != remote]
        self.settings.remotes = [*others, RemoteBinding(remote, list(dict.fromkeys(lights)))]
        self._save_settings()

    def remove_remote(self, remote: str) -> None:
        self.settings.remotes = [b for b in self.settings.remotes if b.remote != remote]
        self._save_settings()

    def remote_list(self) -> list[dict]:
        result = []
        for ieee, device in self.settings.devices.items():
            if device.kind != "remote":
                continue
            memo = self.remote_memo.get(ieee, {})
            press = memo.get("last_press")
            result.append(
                {
                    "ieee": ieee,
                    "name": device.name,
                    "room": device.room,
                    "model": device.model,
                    "configured": device.configured,
                    "battery": memo.get("battery"),
                    "last_action": memo.get("last_action"),
                    "last_press": press.isoformat() if press else None,
                    "firmware": self.firmware.get(ieee),
                    "lights": next(
                        (b.lights for b in self.settings.remotes if b.remote == ieee), []
                    ),
                }
            )
        return result

    # --- master switch -----------------------------------------------------------------

    async def master_switch(self, action: str) -> None:
        """ "off": remember the lit lamps (brightness, warmth, owner) and switch everything
        off. "on": bring the remembered lamps back (motion-lit ones go back to their
        sensor); with nothing ever remembered, every lamp at its last setting by hand.
        Alarms are untouched (a sunrise running right now stops, like any manual off)."""
        if action == "off":
            await self._master_off()
        elif action == "on":
            await self._master_on()
        else:
            raise SettingsError(f"Unknown master action {action!r}")

    async def _master_off(self) -> None:
        memory = {}
        for ieee, controller in self.registry.controllers.items():
            state = controller.state
            if state.on is True:
                kelvin = mired_to_kelvin(state.mireds) if state.mireds else None
                memory[ieee] = {
                    "level": state.level or MAX_LEVEL,
                    "kelvin": kelvin if controller.caps.supports_ct else None,
                    "owner": self.behaviour.lamp(ieee).owner,
                }
        if memory:  # pressed with everything off: keep the old memory
            self.state.master = memory
            self.store.save_state(self.state)
        LOGGER.info("Master off: remembering %s", list(memory) or "nothing new")
        for ieee, controller in self.registry.controllers.items():
            if controller.state.on is not False and controller.available:
                await self.lamp_action(ieee, "off")  # fades out in the background

    async def _master_on(self) -> None:
        memory = self.state.master
        if not memory:
            memory = {ieee: {"owner": "manual"} for ieee in self.registry.light_ieees()}
        LOGGER.info("Master on: restoring %s", list(memory))
        jobs = []
        for ieee, saved in memory.items():
            if ieee not in self.registry.controllers:
                continue  # removed since
            if saved.get("owner") == "motion" and self.behaviour.rule_for_lamp(ieee):
                jobs.append(self.lamp_action(ieee, "auto"))  # back to its sensor
                continue
            last = self.settings.light_settings(ieee).last_manual
            if saved.get("level"):
                last.level = max(MIN_LEVEL, min(MAX_LEVEL, int(saved["level"])))
            if saved.get("kelvin"):
                last.kelvin = max(1500, min(6500, int(saved["kelvin"])))
            jobs.append(self.lamp_action(ieee, "on"))
        self._save_settings()
        results = await asyncio.gather(*jobs, return_exceptions=True)
        failed = [r for r in results if isinstance(r, Exception)]
        for error in failed:
            LOGGER.warning("Master on: %r", error)
        if failed:
            raise LightError(f"{len(failed)} of {len(jobs)} lamps didn't respond")

    def master_status(self) -> dict:
        return {
            "any_on": any(c.state.on is True for c in self.registry.controllers.values()),
            "remembered": sorted(i for i in self.state.master if i in self.registry.controllers),
        }

    def _remember_manual(self, ieee: str, action: str, value: int) -> None:
        """The last level and warmth set by hand (a remote's "on" will restore them)."""
        last = self.settings.light_settings(ieee).last_manual
        if action == "level":
            last.level = max(MIN_LEVEL, min(254, value))
        else:
            last.kelvin = max(1500, min(6500, value))

    def _live_sender(self, ieee: str) -> LatestWins:
        if ieee not in self._live:
            controller = self.registry.controller(ieee)

            async def send(kind: str, value: int) -> None:
                async with controller.lock:
                    if kind == "level":
                        await controller.set_level(value, transition_s=LIVE_TRANSITION_S)
                    else:
                        await controller.set_ct(kelvin_to_mired(value))

            self._live[ieee] = LatestWins(send)
        return self._live[ieee]

    async def refresh_lamp(self, ieee: str) -> None:
        controller = self.registry.controller(ieee)
        async with controller.lock:
            await controller.refresh()

    async def test_sunrise(self, minutes: float) -> None:
        if not 0.5 <= minutes <= MAX_TEST_MINUTES:
            raise SettingsError(f"Test length must be 0.5-{MAX_TEST_MINUTES} minutes")
        ieee = self._require_wakeup()
        await self.stop_sunrise("test sunrise")
        if self.controller.state.on:
            async with self.controller.lock:
                await self.controller.off(park_mireds=self.curve().warm_mired)
            await asyncio.sleep(1)
        now = self.clock.now()
        end = now + timedelta(minutes=minutes)
        run = Run(
            kind="test", start=now, end=end, off=end + timedelta(seconds=TEST_HOLD_S), light=ieee
        )
        self.manager.start(run)
        self._sunrise_started(run)

    async def set_wakeup_light(self, ieee: str | None) -> None:
        if ieee is not None:
            self.registry.controller(ieee)  # must be a known lamp
        previous = self.settings.wakeup.light
        if ieee == previous:
            return
        await self.stop_sunrise("wake-up lamp changed")
        self.settings.wakeup.light = ieee
        lamps = [x for x in (ieee, previous) if x is not None and x in self.registry.controllers]
        for lamp in lamps:
            self._set_power_on_policy(lamp)
        self._save_settings()
        self._attach_wakeup()
        self.scheduler.poke()
        # Writing to the lamps can take seconds (or fail for an unreachable lamp).
        for lamp in lamps:
            self._spawn_logged(self._apply_power_on(lamp), f"Power-on setting for {lamp}")

    def update_alarms(self, alarms: list[dict]) -> None:
        if len(alarms) != 7:
            raise SettingsError("Need 7 alarms")
        new = [Alarm(enabled=bool(a["enabled"]), time=str(a["time"])) for a in alarms]
        for alarm in new:
            alarm.validate()
        self.settings.wakeup.alarms = new
        self._save_settings()
        self.scheduler.poke()

    def update_ramp(self, data: dict) -> None:
        ramp = RampSettings(
            duration_min=int(data["duration_min"]),
            gamma=float(data["gamma"]),
            warm_kelvin=int(data["warm_kelvin"]),
            cool_kelvin=int(data["cool_kelvin"]),
            hold_min=int(data["hold_min"]),
        )
        ramp.validate()
        self.settings.wakeup.ramp = ramp
        self._save_settings()
        self.scheduler.poke()

    async def update_wakeup(self, data: dict) -> None:
        if "alarms" in data:
            self.update_alarms(data["alarms"])
        if "ramp" in data:
            self.update_ramp(data["ramp"])
        if "light" in data:
            await self.set_wakeup_light(data["light"])

    def update_night(self, data: dict) -> None:
        night = NightWindow(start=str(data["start"]), end=str(data["end"]))
        previous, self.settings.night = self.settings.night, night
        try:
            self._save_settings()
        except SettingsError:
            self.settings.night = previous
            raise

    def update_motion(self, sensor: str, data: dict) -> None:
        """Create or replace the motion rule of a sensor."""
        device = self.settings.devices.get(sensor)
        if device is None or device.kind != "motion":
            raise SettingsError(f"{sensor} is not a motion sensor")
        lights = [str(x) for x in data.get("lights", [])]
        for ieee in lights:
            self.registry.controller(ieee)  # must be a lamp
        rule = MotionRule(
            sensor=sensor,
            lights=lights,
            enabled=bool(data.get("enabled", True)),
            dark_lux=None if data.get("dark_lux") is None else int(data["dark_lux"]),
            off_after_min=int(data.get("off_after_min", 5)),
            day=Profile(**data["day"]) if "day" in data else Profile(254, 2700),
            night=Profile(**data["night"]) if "night" in data else Profile(13, 2200),
        )
        previous = self.settings.motion
        self.settings.motion = [r for r in previous if r.sensor != sensor] + [rule]
        try:
            self._save_settings()  # validates: one rule per lamp, sane profiles
        except SettingsError:
            self.settings.motion = previous
            raise

    def remove_motion(self, sensor: str) -> None:
        self.settings.motion = [r for r in self.settings.motion if r.sensor != sensor]
        self._save_settings()

    def update_device(self, ieee: str, data: dict) -> None:
        device = self.settings.devices.get(ieee)
        if device is None:
            raise SettingsError(f"Unknown device {ieee}")
        if "name" in data:
            name = str(data["name"]).strip()
            if not 1 <= len(name) <= MAX_NAME_LEN:
                raise SettingsError(f"Name must be 1-{MAX_NAME_LEN} characters")
            device.name = name
        if "room" in data:
            room = str(data["room"]).strip()
            if len(room) > MAX_NAME_LEN:
                raise SettingsError(f"Room must be at most {MAX_NAME_LEN} characters")
            device.room = room
        self._save_settings()

    async def remove_device(self, ieee: str) -> None:
        if ieee not in self.settings.devices:
            raise SettingsError(f"Unknown device {ieee}")
        if ieee == self.settings.wakeup.light:
            await self.stop_sunrise("lamp removed")
        if self.zigbee is not None and not is_fake(ieee):
            import zigpy.types

            await self.zigbee.remove(zigpy.types.EUI64.convert(ieee))  # leave runs in background
        self.registry.remove(ieee)
        self._live.pop(ieee, None)
        self.behaviour.lamps.pop(ieee, None)
        self.behaviour.sensors.pop(ieee, None)
        self._attach_wakeup()
        self._save_settings()

    def set_skip(self, key: str, skip: bool) -> None:
        if skip and key not in self.state.skipped:
            self.state.skipped.append(key)
        elif not skip and key in self.state.skipped:
            self.state.skipped.remove(key)
        self.store.save_state(self.state)
        self.scheduler.poke()

    async def permit(self, seconds: int) -> None:
        if not 0 <= seconds <= 254:
            raise SettingsError("Pairing time must be 0-254 s")
        if self.zigbee is not None:
            await self.zigbee.permit(time_s=seconds)
        self.pairing_until = self.clock.now() + timedelta(seconds=seconds) if seconds else None

    def _pairing_open(self) -> bool:
        return self.pairing_until is not None and self.pairing_until > self.clock.now()

    # --- state for the UI --------------------------------------------------------------

    def lamp_status(self, ieee: str) -> dict:
        controller = self.registry.controllers[ieee]
        device = self.settings.devices[ieee]
        return {
            "ieee": ieee,
            "name": device.name,
            "room": device.room,
            "model": device.model,
            "paired": self.registry.paired(ieee),
            **self._light_fields(controller),
            "reachable": controller.reachable,
            "last_report": controller.last_report,
            **self._owner_fields(ieee),
            "wakeup": ieee == self.settings.wakeup.light,
            "power_on": self.settings.light_settings(ieee).power_on,
        }

    def _owner_fields(self, ieee: str) -> dict:
        memo = self.behaviour.lamp(ieee)
        return {
            "owner": memo.owner,
            "owner_until": memo.off_at.isoformat() if memo.off_at else None,
            "profile": memo.profile,
            "has_motion": self.behaviour.rule_for_lamp(ieee) is not None,
            "motion_paused": self.behaviour.motion_paused(ieee, self.clock.now()),
        }

    def sensor_list(self) -> list[dict]:
        result = []
        for ieee, device in self.settings.devices.items():
            if device.kind != "motion":
                continue
            memo = self.behaviour.sensor(ieee)
            rule = next((r for r in self.settings.motion if r.sensor == ieee), None)
            result.append(
                {
                    "ieee": ieee,
                    "name": device.name,
                    "room": device.room,
                    "occupied": memo.occupied,
                    "last_report": memo.last_report.isoformat() if memo.last_report else None,
                    "lux": memo.raw_lux,
                    "battery": memo.battery,
                    "configured": device.configured,
                    "rule": asdict(rule) if rule else None,
                }
            )
        return result

    @staticmethod
    def _light_fields(controller: LightController) -> dict:
        state = asdict(controller.state)
        state["kelvin"] = mired_to_kelvin(state["mireds"]) if state["mireds"] else None
        return {
            "available": controller.available,
            "caps": asdict(controller.caps),
            "kelvin_range": kelvin_range(controller.caps),
            "kelvin_step": KELVIN_STEP,
            "state": state,
            "error": controller.last_error,
        }

    def device_list(self) -> list[dict]:
        result = []
        for ieee, device in self.settings.devices.items():
            found = self.registry.discovered.get(ieee)
            result.append(
                {
                    "ieee": ieee,
                    "name": device.name,
                    "room": device.room,
                    "kind": device.kind,
                    "model": device.model,
                    "manufacturer": device.manufacturer,
                    "nwk": found.nwk if found else None,
                    "last_seen": found.last_seen if found else None,
                    "initialized": found.initialized if found else False,
                    "paired": found is not None,
                    "is_light": device.kind == "light",
                    "wakeup": ieee == self.settings.wakeup.light,
                }
            )
        return result

    def snapshot(self) -> dict:
        now = self.clock.now()
        settings, tz = self.settings, self.settings.tz
        wakeup = settings.wakeup
        occs = occurrences(now, wakeup.alarms, wakeup.ramp, tz)
        run = self.manager.active
        pairing = self.pairing_until if self._pairing_open() else None
        alarms = [asdict(a) for a in wakeup.alarms]
        ramp = asdict(wakeup.ramp)
        return {
            "now": now.isoformat(),
            "timezone": settings.timezone,
            "clock_synced": self.clock_synced,
            "radio": {"type": settings.radio.type, "fake": self.fake},
            "lights": [self.lamp_status(ieee) for ieee in self.registry.light_ieees()],
            "wakeup": {"light": wakeup.light, "alarms": alarms, "ramp": ramp},
            "night": asdict(settings.night),
            "sensors": self.sensor_list(),
            "remotes": self.remote_list(),
            "weather": self.weather_status(),
            "master": self.master_status(),
            "sunrise": run.status(now) if run else None,
            "upcoming": [
                {
                    "key": o.key,
                    "label": o.label(tz),
                    "alarm": o.alarm.isoformat(),
                    "start": o.start.isoformat(),
                    "skipped": o.key in self.state.skipped,
                }
                for o in upcoming(now, occs)[:4]
            ],
            "last_run": self.state.last_run,
            "last_test": self.last_test,
            "pairing_until": pairing.isoformat() if pairing else None,
            "last_event": self.last_event,
            "devices": self.device_list(),
            "auth_required": bool(settings.web_token),
        }


async def serve(
    store: Store,
    *,
    host: str,
    port: int,
    fake: bool = False,
    fake_lamps: int = 2,
    fake_sensors: int = 0,
    fake_remotes: int = 0,
) -> int:
    """Run until SIGTERM/SIGINT. Every startup failure returns an exit code, so that
    systemd can restart us: a process that hangs after an error never gets restarted."""
    from kotivalo.web import make_web_app
    from kotivalo.zigbee import NetworkNotFormedError, RadioError

    service = Service(
        store,
        fake=fake,
        fake_lamps=fake_lamps,
        fake_sensors=fake_sensors,
        fake_remotes=fake_remotes,
    )
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, service.request_stop)

    runner = web.AppRunner(make_web_app(service), access_log=None, shutdown_timeout=3)
    try:
        await service.start()
        await runner.setup()
        await web.TCPSite(runner, host, port).start()
    except Exception as exc:
        if isinstance(exc, RadioError):
            LOGGER.error("%s", exc)
        else:
            LOGGER.exception("Startup failed")
        await runner.cleanup()
        await service.stop()
        return EXIT_CONFIG if isinstance(exc, NetworkNotFormedError) else 1

    systemd.notify("READY=1")
    service.start_watchdog()
    LOGGER.info("Web UI on http://%s:%d (%s)", host, port, "fake lamps" if fake else "zigbee")
    try:
        await service.stopped.wait()
    finally:
        systemd.notify("STOPPING=1")
        await runner.cleanup()
        await service.stop()
    return service.exit_code
