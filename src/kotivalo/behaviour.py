"""Who controls each lamp: off, manual, motion or sunrise (the owner model).

Pure logic: inputs go in with an explicit time, actions come out. Nothing here
talks to lamps or sleeps; the service runs the actions and calls tick() at
next_deadline().

Rules (docs/ROADMAP.md and the phase 4 plan):
- Motion switches on a lamp that is off, if it is dark (or night), with the night
  profile inside the night window and the day profile otherwise. The profile is
  fixed for that motion period.
- A motion lamp switches off `off_after_min` after the room is empty.
- Manual wins: a lamp switched on from the UI or a remote is never switched off by
  motion. After a manual off, motion is ignored until the room has been empty for
  `off_after_min` (you can switch it off and walk out).
- A lamp seen on/off by other means (wall switch, a report) follows: on means
  manual, off means off.
- Sunrise: owns the lamp while it runs. At the end of its hold the lamp stays on
  if it was manual before, or if there was motion recently (it becomes motion).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from kotivalo.settings import MotionRule, NightWindow, Settings

STUCK_SENSOR_S = 600  # no report this long while "occupied" means empty (dead battery, lost frame)
LUX_SETTLE_S = 60  # lux counts only when the sensor's lamps have been off this long


@dataclass(frozen=True)
class SwitchOn:
    ieee: str
    level: int
    kelvin: int


@dataclass(frozen=True)
class SwitchOff:
    ieee: str


Action = SwitchOn | SwitchOff


@dataclass
class LampMemo:
    owner: str = "off"  # off | manual | motion | sunrise
    off_at: datetime | None = None  # motion: switch off then (None while occupied)
    profile: str | None = None  # motion: "day" or "night", fixed for the period
    before_sunrise: str | None = None  # owner when the sunrise started
    suppressed: bool = False  # manual off while occupied: ignore motion until empty...
    suppressed_until: datetime | None = None  # ...and then for off_after_min more
    off_since: datetime | None = None  # when it was last switched off (lux validity)


@dataclass
class SensorMemo:
    occupied: bool = False
    last_report: datetime | None = None
    last_motion: datetime | None = None
    empty_since: datetime | None = None  # when it last reported the room empty
    lux: float | None = None  # last lux measured with its lamps off (trustworthy)
    raw_lux: float | None = None  # last lux measured, whatever the lamps did
    battery: float | None = None  # percent


def night_now(
    now: datetime, tz: ZoneInfo, window: NightWindow, ramp_start: datetime | None
) -> bool:
    """Inside the night window, which ends early once that morning's sunrise starts."""
    local = now.astimezone(tz)
    start, end = time.fromisoformat(window.start), time.fromisoformat(window.end)
    t = local.time()
    inside = start <= t < end if start <= end else t >= start or t < end
    return inside and not (ramp_start is not None and ramp_start <= now)


class Behaviour:
    def __init__(self, settings: Settings):
        self.settings = settings  # read live: rules can change at any time
        self.lamps: dict[str, LampMemo] = {}
        self.sensors: dict[str, SensorMemo] = {}

    # --- lookups -------------------------------------------------------------------

    def lamp(self, ieee: str) -> LampMemo:
        return self.lamps.setdefault(ieee, LampMemo())

    def sensor(self, ieee: str) -> SensorMemo:
        return self.sensors.setdefault(ieee, SensorMemo())

    def rule_for_sensor(self, sensor: str) -> MotionRule | None:
        return next((r for r in self.settings.motion if r.sensor == sensor and r.enabled), None)

    def rule_for_lamp(self, ieee: str) -> MotionRule | None:
        return next((r for r in self.settings.motion if ieee in r.lights and r.enabled), None)

    # --- inputs --------------------------------------------------------------------

    def motion(self, sensor: str, occupied: bool, now: datetime, night: bool) -> list[Action]:
        memo = self.sensor(sensor)
        memo.last_report = now
        if occupied:
            memo.last_motion, memo.empty_since = now, None
        elif memo.occupied or memo.empty_since is None:
            memo.empty_since = now
        memo.occupied = occupied
        rule = self.rule_for_sensor(sensor)
        if rule is None:
            return []
        actions: list[Action] = []
        after = timedelta(minutes=rule.off_after_min)
        for ieee in rule.lights:
            lamp = self.lamp(ieee)
            if occupied:
                if lamp.suppressed or (lamp.suppressed_until and now < lamp.suppressed_until):
                    lamp.suppressed, lamp.suppressed_until = True, None  # wait until empty
                    continue
                lamp.suppressed_until = None
                if lamp.owner == "off" and (night or self._dark(rule, memo)):
                    profile = rule.night if night else rule.day
                    lamp.owner, lamp.off_at = "motion", None
                    lamp.profile = "night" if night else "day"
                    actions.append(SwitchOn(ieee, profile.level, profile.kelvin))
                elif lamp.owner == "motion":
                    lamp.off_at = None
            else:
                # Counted from when the room became empty: the sensor repeats "empty" every
                # few minutes as a keep-alive, and that must not keep postponing the off.
                if lamp.owner == "motion" and lamp.off_at is None:
                    lamp.off_at = memo.empty_since + after
                if lamp.suppressed:
                    lamp.suppressed, lamp.suppressed_until = False, memo.empty_since + after
        return actions

    def lux(self, sensor: str, lux: float, now: datetime) -> None:
        memo = self.sensor(sensor)
        memo.raw_lux = lux
        rule = self.rule_for_sensor(sensor)
        lamps = [self.lamp(i) for i in rule.lights] if rule else []
        settled = all(
            lamp.owner == "off"
            and (lamp.off_since is None or (now - lamp.off_since).total_seconds() >= LUX_SETTLE_S)
            for lamp in lamps
        )
        if settled:  # the lamps' own light would make the room look bright
            memo.lux = lux

    def battery(self, sensor: str, percent: float) -> None:
        self.sensor(sensor).battery = percent

    def manual(self, ieee: str, on: bool, now: datetime) -> None:
        """Switched from the UI or a remote: manual wins."""
        lamp = self.lamp(ieee)
        lamp.off_at, lamp.profile, lamp.before_sunrise = None, None, None
        if on:
            lamp.owner = "manual"
            lamp.suppressed, lamp.suppressed_until = False, None
            return
        lamp.owner, lamp.off_since = "off", now
        rule = self.rule_for_lamp(ieee)
        if rule is not None:
            if self.sensor(rule.sensor).occupied:
                lamp.suppressed, lamp.suppressed_until = True, None
            else:
                lamp.suppressed_until = now + timedelta(minutes=rule.off_after_min)

    def automatic(self, ieee: str, lamp_on: bool, now: datetime, night: bool) -> list[Action]:
        """Hand the lamp back to its motion sensor ("let motion control it"): clears a
        manual setting or a pause. An occupied, dark room switches an off lamp on now."""
        rule = self.rule_for_lamp(ieee)
        lamp = self.lamp(ieee)
        if rule is None or lamp.owner == "sunrise":
            return []
        lamp.suppressed, lamp.suppressed_until, lamp.before_sunrise = False, None, None
        memo = self.sensor(rule.sensor)
        after = timedelta(minutes=rule.off_after_min)
        if lamp_on:
            lamp.owner, lamp.profile = "motion", lamp.profile or ("night" if night else "day")
            lamp.off_at = None if memo.occupied else now + after
            return []
        lamp.owner, lamp.off_at, lamp.profile = "off", None, None
        if memo.occupied and (night or self._dark(rule, memo)):
            profile = rule.night if night else rule.day
            lamp.owner, lamp.profile = "motion", "night" if night else "day"
            return [SwitchOn(ieee, profile.level, profile.kelvin)]
        return []

    def lamp_state(self, ieee: str, on: bool, now: datetime) -> None:
        """The lamp was seen on or off (a report or a poll), e.g. its wall switch."""
        lamp = self.lamp(ieee)
        if not on and lamp.owner in ("manual", "motion"):
            lamp.owner, lamp.off_at, lamp.profile, lamp.off_since = "off", None, None, now
        elif on and lamp.owner == "off":
            lamp.owner = "manual"

    def sunrise_started(self, ieee: str) -> None:
        lamp = self.lamp(ieee)
        lamp.before_sunrise = lamp.owner if lamp.owner != "sunrise" else lamp.before_sunrise
        lamp.owner, lamp.off_at, lamp.profile = "sunrise", None, None

    def keep_on_after_sunrise(self, ieee: str, now: datetime) -> bool:
        """End of the sunrise hold: stay on for a manual lamp or an occupied room."""
        lamp = self.lamp(ieee)
        if lamp.before_sunrise == "manual":
            lamp.owner, lamp.before_sunrise = "manual", None
            return True
        rule = self.rule_for_lamp(ieee)
        if rule is not None:
            memo = self.sensor(rule.sensor)
            after = timedelta(minutes=rule.off_after_min)
            recent = memo.empty_since is not None and now - memo.empty_since < after
            if memo.occupied or recent:
                lamp.owner, lamp.profile, lamp.before_sunrise = "motion", "day", None
                lamp.off_at = None if memo.occupied else memo.empty_since + after
                return True
        return False

    def sunrise_ended(self, ieee: str, lamp_on: bool, now: datetime) -> None:
        lamp = self.lamp(ieee)
        if lamp.owner != "sunrise":
            return  # already handed over (keep_on_after_sunrise)
        lamp.before_sunrise = None
        if lamp_on:
            lamp.owner = "manual"  # stays on (no auto-off, or a manual action ends it next)
        else:
            lamp.owner, lamp.off_since = "off", now

    def motion_paused(self, ieee: str, now: datetime) -> bool:
        """After a manual off: motion is ignored for now."""
        lamp = self.lamp(ieee)
        return lamp.suppressed or (
            lamp.suppressed_until is not None and now < lamp.suppressed_until
        )

    def why_not_on(self, ieee: str, sensor: str, now: datetime, night: bool) -> str | None:
        """Why motion left this lamp as it is (for the log), or None if it switched it."""
        lamp, memo = self.lamp(ieee), self.sensor(sensor)
        rule = self.rule_for_sensor(sensor)
        if lamp.owner != "off":
            return f"it is {lamp.owner}" + (
                " (switched by hand: manual wins)" if lamp.owner == "manual" else ""
            )
        if self.motion_paused(ieee, now):
            return "motion is paused after a manual off, until the room has been empty for a while"
        if rule and not night and not self._dark(rule, memo):
            return f"the room is bright ({memo.lux} lx >= {rule.dark_lux} lx)"
        return None

    # --- time ----------------------------------------------------------------------

    def tick(self, now: datetime) -> list[Action]:
        actions: list[Action] = []
        for sensor, memo in self.sensors.items():
            stale = memo.last_report and (now - memo.last_report).total_seconds() >= STUCK_SENSOR_S
            if memo.occupied and stale:
                actions += self.motion(sensor, False, now, night=False)
        for ieee, lamp in self.lamps.items():
            if lamp.owner == "motion" and lamp.off_at is not None and lamp.off_at <= now:
                lamp.owner, lamp.off_at, lamp.profile, lamp.off_since = "off", None, None, now
                actions.append(SwitchOff(ieee))
        return actions

    def next_deadline(self) -> datetime | None:
        times = [
            lamp.off_at for lamp in self.lamps.values() if lamp.owner == "motion" and lamp.off_at
        ]
        times += [
            memo.last_report + timedelta(seconds=STUCK_SENSOR_S)
            for memo in self.sensors.values()
            if memo.occupied and memo.last_report
        ]
        return min(times, default=None)

    # --- persistence (state.json) ----------------------------------------------------

    def to_dict(self) -> dict:
        def encode(memo: LampMemo) -> dict:
            data = asdict(memo)
            for key in ("off_at", "suppressed_until", "off_since"):
                data[key] = data[key].isoformat() if data[key] else None
            return data

        return {ieee: encode(lamp) for ieee, lamp in self.lamps.items()}

    def load(self, data: dict) -> None:
        for ieee, raw in (data or {}).items():
            memo = LampMemo(**{k: v for k, v in raw.items() if k in LampMemo.__dataclass_fields__})
            for key in ("off_at", "suppressed_until", "off_since"):
                value = getattr(memo, key)
                setattr(memo, key, datetime.fromisoformat(value) if value else None)
            self.lamps[ieee] = memo

    def _dark(self, rule: MotionRule, memo: SensorMemo) -> bool:
        if rule.dark_lux is None or memo.lux is None:
            return True  # no threshold, or no trustworthy reading yet
        return memo.lux < rule.dark_lux
