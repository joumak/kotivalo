"""The long-running service: radio, light, scheduler and web UI in one asyncio process."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from dataclasses import asdict
from datetime import datetime, timedelta

from aiohttp import web

from wakeup_light.clock import Clock, ntp_synchronized
from wakeup_light.light import FakeLight, LightCaps, LightController, LightError
from wakeup_light.ramp import (
    KELVIN_STEP,
    Curve,
    kelvin_range,
    kelvin_to_mired,
    mired_to_kelvin,
)
from wakeup_light.schedule import occurrences, upcoming
from wakeup_light.scheduler import AlarmScheduler, prune_skipped
from wakeup_light.settings import Alarm, RampSettings, SettingsError, Store
from wakeup_light.sunrise import Run, SunriseManager

LOGGER = logging.getLogger(__name__)

EXIT_CONFIG = 78
RADIO_CHECK_INTERVAL_S = 60
CLOCK_CHECK_INTERVAL_S = 60
STOP_TIMEOUT_S = 5
TEST_HOLD_S = 30
MAX_TEST_MINUTES = 60
FAKE_IEEE = "00:00:00:00:00:00:00:01"


class Service:
    def __init__(self, store: Store, *, fake: bool = False, clock: Clock | None = None):
        self.store = store
        self.fake = fake
        self.clock = clock or Clock()
        self.settings = store.load_settings()
        self.state = store.load_state()
        self.controller = LightController(None, self.settings.caps)
        self.manager = SunriseManager(self.controller, self.clock, self.curve, self._finished)
        self.scheduler = AlarmScheduler(
            self.manager, self.clock, lambda: self.settings, lambda: self.state
        )
        self.zigbee = None  # zigpy ControllerApplication
        self.clock_synced: bool | None = None
        self.pairing_until: datetime | None = None
        self.last_event: str | None = None
        self.last_test: dict | None = None
        self.stopped = asyncio.Event()
        self.exit_code = 0
        self._tasks: list[asyncio.Task] = []

    # --- lifecycle ---------------------------------------------------------------

    def curve(self) -> Curve:
        return Curve.from_settings(self.settings.ramp, self.controller.caps)

    async def start(self) -> None:
        if self.fake:
            self.controller.light = FakeLight(clock=self.clock)
            self.controller.caps = self.controller.light.caps
            self.settings.target_ieee = FAKE_IEEE
        else:
            from wakeup_light.zigbee import DeviceEvents, start_app

            self.zigbee = await start_app(self.settings.radio, self.store.db_path)
            self.zigbee.add_listener(DeviceEvents(self._device_event))
            self._attach_light()
            self._spawn(self._radio_watch())
        with contextlib.suppress(LightError):
            await self.controller.refresh()
        self._spawn(self.scheduler.run_forever())
        self._spawn(self._clock_watch())

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

    def request_stop(self, exit_code: int = 0) -> None:
        self.exit_code = exit_code
        self.stopped.set()

    def _spawn(self, coro) -> None:
        self._tasks.append(asyncio.create_task(coro))

    def _attach_light(self) -> None:
        from wakeup_light.zigbee import ZigbeeLight

        ieee = self.settings.target_ieee
        self.controller.light = ZigbeeLight(self.zigbee, ieee) if ieee else None
        self.controller.caps = self.settings.caps or LightCaps()

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
            self.clock_synced = await ntp_synchronized()
            if prune_skipped(self.state, self.clock.now()):
                self.store.save_state(self.state)
            await asyncio.sleep(CLOCK_CHECK_INTERVAL_S)

    def _device_event(self, kind: str, obj) -> None:
        from wakeup_light.zigbee import light_endpoint

        if kind == "connection_lost":
            if obj is not None:
                LOGGER.error("Radio connection lost: %r", obj)
                self.request_stop(1)
            return
        name = f"{obj.manufacturer or ''} {obj.model or ''}".strip() or str(obj.ieee)
        self.last_event = f"{kind}: {name} ({obj.ieee})"
        LOGGER.info("Device %s", self.last_event)
        if kind == "initialized" and light_endpoint(obj) and not self.settings.target_ieee:
            asyncio.create_task(self.select_light(str(obj.ieee)))

    async def _finished(self, run: Run, result: str) -> None:
        if result == "interrupted":
            return  # process shutdown: resume after restart
        record = {
            "kind": run.kind,
            "key": run.key,
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

    # --- actions (called by the web API) --------------------------------------------

    async def stop_sunrise(self, reason: str) -> None:
        run = await self.manager.cancel(reason)
        if run is not None and run.key and run.key not in self.state.skipped:
            self.state.skipped.append(run.key)  # don't let the scheduler restart it
            self.store.save_state(self.state)

    async def light_action(self, action: str, value: float | None = None) -> None:
        await self.stop_sunrise("manual control")
        async with self.controller.lock:
            match action:
                case "on":
                    await self.controller.on()
                case "off":
                    await self.controller.off(park_mireds=self.curve().warm_mired)
                case "level":
                    await self.controller.set_level(int(value), transition_s=0.5)
                case "kelvin":
                    await self.controller.set_ct(kelvin_to_mired(value))
                case _:
                    raise SettingsError(f"Unknown light action {action!r}")

    async def refresh_light(self) -> None:
        async with self.controller.lock:
            await self.controller.refresh()

    async def test_sunrise(self, minutes: float) -> None:
        if not 0.5 <= minutes <= MAX_TEST_MINUTES:
            raise SettingsError(f"Test length must be 0.5-{MAX_TEST_MINUTES} minutes")
        await self.stop_sunrise("test sunrise")
        if self.controller.state.on:
            async with self.controller.lock:
                await self.controller.off(park_mireds=self.curve().warm_mired)
            await asyncio.sleep(1)
        now = self.clock.now()
        end = now + timedelta(minutes=minutes)
        self.manager.start(
            Run(kind="test", start=now, end=end, off=end + timedelta(seconds=TEST_HOLD_S))
        )

    def update_alarms(self, alarms: list[dict]) -> None:
        if len(alarms) != 7:
            raise SettingsError("Need 7 alarms")
        new = [Alarm(enabled=bool(a["enabled"]), time=str(a["time"])) for a in alarms]
        for alarm in new:
            alarm.validate()
        self.settings.alarms = new
        self.store.save_settings(self.settings)
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
        self.settings.ramp = ramp
        self.store.save_settings(self.settings)
        self.scheduler.poke()

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

    async def select_light(self, ieee: str) -> None:
        from wakeup_light.zigbee import ZigbeeLight

        if self.fake:
            return
        light = ZigbeeLight(self.zigbee, ieee)
        caps = await light.read_caps()
        await light.restore_after_power_loss()
        self.settings.target_ieee, self.settings.caps = ieee, caps
        self.store.save_settings(self.settings)
        self._attach_light()
        LOGGER.info("Alarm light is now %s (%s)", ieee, caps.model)

    # --- state for the UI --------------------------------------------------------------

    def devices(self) -> list[dict]:
        if self.fake:
            return [
                {
                    "ieee": FAKE_IEEE, "nwk": "0x0001", "manufacturer": "Test",
                    "model": "Fake panel", "initialized": True, "is_light": True,
                    "last_seen": self.clock.now().timestamp(),
                }
            ]  # fmt: skip
        from wakeup_light.zigbee import devices

        return devices(self.zigbee) if self.zigbee is not None else []

    def snapshot(self) -> dict:
        now = self.clock.now()
        settings, tz = self.settings, self.settings.tz
        occs = occurrences(now, settings.alarms, settings.ramp, tz)
        run = self.manager.active
        caps = self.controller.caps
        light_state = asdict(self.controller.state)
        light_state["kelvin"] = (
            mired_to_kelvin(light_state["mireds"]) if light_state["mireds"] else None
        )
        pairing = self.pairing_until if self.pairing_until and self.pairing_until > now else None
        return {
            "now": now.isoformat(),
            "timezone": settings.timezone,
            "clock_synced": self.clock_synced,
            "radio": {"type": settings.radio.type, "fake": self.fake},
            "light": {
                "ieee": settings.target_ieee,
                "available": self.controller.available,
                "caps": asdict(caps),
                "kelvin_range": kelvin_range(caps),
                "kelvin_step": KELVIN_STEP,
                "state": light_state,
                "error": self.controller.last_error,
            },
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
            "alarms": [asdict(a) for a in settings.alarms],
            "ramp": asdict(settings.ramp),
            "last_run": self.state.last_run,
            "last_test": self.last_test,
            "pairing_until": pairing.isoformat() if pairing else None,
            "last_event": self.last_event,
            "devices": self.devices(),
            "auth_required": bool(settings.web_token),
        }


async def serve(store: Store, *, host: str, port: int, fake: bool = False) -> int:
    from wakeup_light.web import make_web_app

    service = Service(store, fake=fake)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, service.request_stop)

    try:
        await service.start()
    except Exception as exc:
        from wakeup_light.zigbee import NetworkNotFormedError, RadioError

        if isinstance(exc, NetworkNotFormedError):
            LOGGER.error("%s", exc)
            return EXIT_CONFIG
        if isinstance(exc, RadioError):
            LOGGER.error("%s", exc)
            return 1
        raise

    runner = web.AppRunner(make_web_app(service), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    LOGGER.info("Web UI on http://%s:%d (%s)", host, port, "fake light" if fake else "zigbee")
    try:
        await service.stopped.wait()
    finally:
        await runner.cleanup()
        await service.stop()
    return service.exit_code
