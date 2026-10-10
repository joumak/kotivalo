"""The long-running service: radio, lamps, scheduler and web UI in one asyncio process."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import time
from dataclasses import asdict
from datetime import datetime, timedelta

from aiohttp import web

from kotivalo import systemd
from kotivalo.clock import Clock, ntp_synchronized
from kotivalo.events import Announce, Event, LightReport
from kotivalo.light import FakeLight, LatestWins, LightController, LightError
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
    NightWindow,
    RampSettings,
    SettingsError,
    Store,
    is_fake,
)
from kotivalo.sunrise import Run, SunriseManager

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


def poll_delay(failures: int) -> float:
    """Seconds until the next poll: every minute, backing off to 10 min while a lamp
    does not answer (each poll of a missing lamp costs route discovery on the XBee)."""
    return float(min(POLL_MAX_S, POLL_INTERVAL_S * 2**failures))


def fake_devices(lamps: int) -> list[Discovered]:
    return [
        Discovered(f"{FAKE_PREFIX}{i:02x}", "light", "Fake panel", "Test", 1)
        for i in range(1, lamps + 1)
    ]


class Service:
    def __init__(
        self, store: Store, *, fake: bool = False, fake_lamps: int = 2, clock: Clock | None = None
    ):
        self.store = store
        self.fake = fake
        self.fake_lamps = fake_lamps
        self.clock = clock or Clock()
        self.settings = store.load_settings()
        self.state = store.load_state()
        self.registry = Registry(self.settings, self._make_light)
        self.manager = SunriseManager(LightController(None), self.clock, self.curve, self._finished)
        self.scheduler = AlarmScheduler(
            self.manager,
            self.clock,
            lambda: self.settings,
            lambda: self.state,
            on_start=lambda run: self.notify(),
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
            found = fake_devices(self.fake_lamps)
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
        self._spawn(self.scheduler.run_forever())
        self._spawn(self._clock_watch())
        self._spawn(self._ticker())
        self._spawn(self._consume_events())
        self._spawn(self._poll_lamps())
        if self.zigbee is not None:
            self._spawn_logged(self._configure_lamps(), "Configuring lamp reporting")

    async def stop(self) -> None:
        await self.manager.shutdown()
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

    async def _consume_events(self) -> None:
        """Every device event, in one place."""
        while True:
            event = await self.events.get()
            try:
                self._handle_event(event)
            except Exception:
                LOGGER.exception("Handling %r failed", event)

    def _handle_event(self, event: Event) -> None:
        controller = self.registry.controllers.get(event.ieee)
        if controller is None:
            return
        match event:
            case LightReport(attribute=attribute, value=value):
                if controller.apply_report(attribute, value):
                    self.notify()
            case Announce():
                # Typically a lamp that just got mains power back (a wall switch).
                LOGGER.info("Lamp %s announced itself; reading its state", event.ieee)
                self._spawn_logged(self._refresh_soon(event.ieee), f"Refreshing {event.ieee}")

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
                with contextlib.suppress(LightError, TimeoutError):
                    await self._poll_lamp(controller)
                next_poll[ieee] = time.monotonic() + poll_delay(controller.failures)
                if (controller.reachable, asdict(controller.state)) != before:
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
        if ieee == self.settings.wakeup.light:
            await self.stop_sunrise("manual control")
        match action:
            case "on" | "off" | "toggle":
                async with controller.lock:
                    if action == "toggle":
                        action = "off" if controller.state.on else "on"
                    if action == "on":
                        await controller.on()
                    else:
                        park = controller.caps.max_mireds if controller.caps.supports_ct else None
                        await controller.off(park_mireds=park)
            case "level" | "kelvin":
                if value is None:
                    raise SettingsError(f"{action} needs a value")
                await self._live_sender(ieee).submit(action, int(value))
            case _:
                raise SettingsError(f"Unknown light action {action!r}")

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
        self.manager.start(
            Run(
                kind="test",
                start=now,
                end=end,
                off=end + timedelta(seconds=TEST_HOLD_S),
                light=ieee,
            )
        )

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
            "wakeup": ieee == self.settings.wakeup.light,
            "power_on": self.settings.light_settings(ieee).power_on,
            "owner": None,  # filled in by the behaviour layer (phase 3/4)
        }

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
    store: Store, *, host: str, port: int, fake: bool = False, fake_lamps: int = 2
) -> int:
    """Run until SIGTERM/SIGINT. Every startup failure returns an exit code, so that
    systemd can restart us: a process that hangs after an error never gets restarted."""
    from kotivalo.web import make_web_app
    from kotivalo.zigbee import NetworkNotFormedError, RadioError

    service = Service(store, fake=fake, fake_lamps=fake_lamps)
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
