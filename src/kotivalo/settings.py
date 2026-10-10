"""Persisted configuration (settings.json) and runtime state (state.json).

settings.json is versioned. A version 1 file (the single-lamp wakeup light) is
migrated on load; the original is kept as settings.v1.json.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
import types
import typing
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kotivalo.light import MAX_LEVEL, MIN_LEVEL, LightCaps

LOGGER = logging.getLogger(__name__)

SETTINGS_VERSION = 2
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
RADIO_TYPES = ("xbee", "ezsp", "znp")
DEVICE_KINDS = ("light", "motion", "remote", "other")
POWER_ON = ("on", "previous")  # what a lamp does when mains power returns
FAKE_PREFIX = "00:00:00:00:00:00:00:"  # `serve --fake` devices: never saved


class SettingsError(ValueError):
    pass


def _check_time(value: str, what: str) -> None:
    if not TIME_RE.match(value):
        raise SettingsError(f"{what} must be HH:MM, got {value!r}")


def default_name(model: str | None, ieee: str) -> str:
    """A name for a device the user has not named yet, e.g. 'FLOALT panel WS 60x60 e52c'
    or 'STYRBAR 1a2b' (the box name rather than a remote's model id)."""
    from kotivalo.remotes import PRODUCT_NAMES

    return f"{PRODUCT_NAMES.get(model or '', model) or 'Device'} {ieee.replace(':', '')[-4:]}"


def is_fake(ieee: str | None) -> bool:
    return bool(ieee) and ieee.startswith(FAKE_PREFIX)


@dataclass
class Alarm:
    enabled: bool = False
    time: str = "07:00"  # local wall-clock HH:MM

    def validate(self) -> None:
        _check_time(self.time, "Alarm time")


@dataclass
class RampSettings:
    duration_min: int = 30
    gamma: float = 2.5  # >1 keeps the start dim for longer
    warm_kelvin: int = 2200
    cool_kelvin: int = 4000
    hold_min: int = 60  # switch off this long after the alarm; 0 = leave on

    def validate(self) -> None:
        if not 1 <= self.duration_min <= 120:
            raise SettingsError("Ramp duration must be 1-120 minutes")
        if not 1.0 <= self.gamma <= 4.0:
            raise SettingsError("Gamma must be between 1 and 4")
        if not 1500 <= self.warm_kelvin <= self.cool_kelvin <= 6500:
            raise SettingsError("Need 1500 <= warm K <= cool K <= 6500")
        if not 0 <= self.hold_min <= 720:
            raise SettingsError("Auto-off must be 0-720 minutes")


@dataclass
class RadioSettings:
    type: str = "xbee"
    path: str = "/dev/serial/by-id/usb-Digi_XStick-if00-port0"
    baudrate: int = 57600
    flow_control: str | None = None  # ezsp only: "software" or "hardware"
    channel: int = 15  # used only by form-network

    def validate(self) -> None:
        if self.type not in RADIO_TYPES:
            raise SettingsError(f"Radio type must be one of {RADIO_TYPES}")
        if not 11 <= self.channel <= 26:
            raise SettingsError("Zigbee channel must be 11-26")


@dataclass
class Profile:
    """A brightness and colour temperature to switch a lamp on with."""

    level: int = MAX_LEVEL
    kelvin: int = 2700

    def validate(self, what: str) -> None:
        if not MIN_LEVEL <= self.level <= MAX_LEVEL:
            raise SettingsError(f"{what}: level must be {MIN_LEVEL}-{MAX_LEVEL}")
        if not 1500 <= self.kelvin <= 6500:
            raise SettingsError(f"{what}: kelvin must be 1500-6500")


@dataclass
class Device:
    name: str = ""
    room: str = ""
    kind: str = "other"  # one of DEVICE_KINDS
    model: str | None = None
    manufacturer: str | None = None
    endpoint: int | None = None  # the light endpoint, for lamps
    configured: bool = False  # bindings and reporting set up (later phases)


@dataclass
class LightSettings:
    caps: LightCaps = field(default_factory=LightCaps)
    power_on: str = "on"  # "on": the wall switch works; "previous": a power cut keeps it off
    last_manual: Profile = field(default_factory=Profile)


@dataclass
class WakeupSettings:
    light: str | None = None  # IEEE of the wake-up lamp
    alarms: list[Alarm] = field(default_factory=lambda: [Alarm() for _ in WEEKDAYS])
    ramp: RampSettings = field(default_factory=RampSettings)


@dataclass
class NightWindow:
    """Shared by the motion night light and the wall panel's night mode."""

    start: str = "23:00"
    end: str = "07:00"


@dataclass
class WeatherSettings:
    """Where to show the weather for. Coordinates are kept to 2 decimals (about 1 km)."""

    name: str = ""
    lat: float | None = None
    lon: float | None = None

    @property
    def enabled(self) -> bool:
        return self.lat is not None and self.lon is not None

    def validate(self) -> None:
        if len(self.name) > 40:
            raise SettingsError("Weather place name must be at most 40 characters")
        if self.lat is not None and not -90 <= self.lat <= 90:
            raise SettingsError("Latitude must be -90..90")
        if self.lon is not None and not -180 <= self.lon <= 180:
            raise SettingsError("Longitude must be -180..180")


@dataclass
class MotionRule:
    sensor: str = ""
    lights: list[str] = field(default_factory=list)
    enabled: bool = True
    dark_lux: int | None = 30  # switch on only below this; None = always
    off_after_min: int = 5
    day: Profile = field(default_factory=lambda: Profile(MAX_LEVEL, 2700))
    night: Profile = field(default_factory=lambda: Profile(13, 2200))


@dataclass
class RemoteBinding:
    remote: str = ""
    lights: list[str] = field(default_factory=list)


@dataclass
class Settings:
    version: int = SETTINGS_VERSION
    timezone: str = "Europe/Helsinki"
    radio: RadioSettings = field(default_factory=RadioSettings)
    devices: dict[str, Device] = field(default_factory=dict)
    lights: dict[str, LightSettings] = field(default_factory=dict)
    wakeup: WakeupSettings = field(default_factory=WakeupSettings)
    night: NightWindow = field(default_factory=NightWindow)
    motion: list[MotionRule] = field(default_factory=list)
    remotes: list[RemoteBinding] = field(default_factory=list)
    weather: WeatherSettings = field(default_factory=WeatherSettings)
    web_token: str | None = None  # if set, the web API requires it

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def light_settings(self, ieee: str) -> LightSettings:
        return self.lights.setdefault(ieee, LightSettings())

    def validate(self) -> None:
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise SettingsError(f"Unknown timezone {self.timezone!r}") from exc
        self.radio.validate()
        if len(self.wakeup.alarms) != 7:
            raise SettingsError("Need exactly 7 alarms (Mon..Sun)")
        for alarm in self.wakeup.alarms:
            alarm.validate()
        self.wakeup.ramp.validate()
        _check_time(self.night.start, "Night start")
        _check_time(self.night.end, "Night end")
        self.weather.validate()
        for ieee, device in self.devices.items():
            if device.kind not in DEVICE_KINDS:
                raise SettingsError(f"{ieee}: unknown device kind {device.kind!r}")
        for ieee, light in self.lights.items():
            if light.power_on not in POWER_ON:
                raise SettingsError(f"{ieee}: power_on must be one of {POWER_ON}")
            light.last_manual.validate(f"{ieee} last manual")
        ruled: set[str] = set()
        for rule in self.motion:
            rule.day.validate("Motion day profile")
            rule.night.validate("Motion night profile")
            if not 1 <= rule.off_after_min <= 240:
                raise SettingsError("Motion off-after must be 1-240 minutes")
            if clash := ruled.intersection(rule.lights):
                raise SettingsError(f"A lamp can have only one motion rule: {sorted(clash)}")
            ruled.update(rule.lights)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        if data.get("version", 1) < SETTINGS_VERSION:
            data = migrate_v1(data)
        settings = _build(cls, data)
        settings.version = SETTINGS_VERSION
        settings.validate()
        return settings

    def to_dict(self) -> dict[str, Any]:
        """Everything except the `serve --fake` devices."""
        data = asdict(self)
        data["devices"] = {k: v for k, v in data["devices"].items() if not is_fake(k)}
        data["lights"] = {k: v for k, v in data["lights"].items() if not is_fake(k)}
        if is_fake(data["wakeup"]["light"]):
            data["wakeup"]["light"] = None
        data["motion"] = [
            {**rule, "lights": [x for x in rule["lights"] if not is_fake(x)]}
            for rule in data["motion"]
            if not is_fake(rule["sensor"])
        ]
        data["remotes"] = [
            {**bind, "lights": [x for x in bind["lights"] if not is_fake(x)]}
            for bind in data["remotes"]
            if not is_fake(bind["remote"])
        ]
        return data


def migrate_v1(data: dict[str, Any]) -> dict[str, Any]:
    """Version 1 (one wakeup lamp: target_ieee, caps, alarms, ramp) to version 2."""
    target = data.get("target_ieee")
    caps = data.get("caps") or {}
    devices, lights = {}, {}
    if target:
        devices[target] = {
            "name": default_name(caps.get("model"), target),
            "kind": "light",
            "model": caps.get("model"),
            "manufacturer": caps.get("manufacturer"),
        }
        # The wake-up lamp keeps its state over a power cut, so a night-time cut
        # does not switch it on (this is what version 1 configured on the lamp).
        lights[target] = {"caps": caps, "power_on": "previous"}
    return {
        "version": SETTINGS_VERSION,
        "timezone": data.get("timezone", "Europe/Helsinki"),
        "radio": data.get("radio", {}),
        "web_token": data.get("web_token"),
        "devices": devices,
        "lights": lights,
        "wakeup": {
            "light": target,
            "alarms": data.get("alarms", [{} for _ in WEEKDAYS]),
            "ramp": data.get("ramp", {}),
        },
    }


@dataclass
class State:
    """Small runtime facts that must survive a restart."""

    skipped: list[str] = field(default_factory=list)  # alarm keys (UTC ISO) skipped or stopped
    last_run: dict[str, Any] | None = None
    behaviour: dict[str, Any] = field(default_factory=dict)  # owner per lamp (behaviour.py)
    # The lamps lit at the last master-off: {ieee: {level, kelvin, owner}}. Kept until the
    # next master-off, so the master switch always brings back "my usual lights".
    master: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> State:
        return _build(cls, data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _build(cls, data: Any):
    """Construct a (nested) dataclass from parsed JSON, ignoring unknown keys."""
    if not isinstance(data, dict):
        raise SettingsError(f"Expected an object for {cls.__name__}")
    hints = typing.get_type_hints(cls)
    kwargs = {f.name: _convert(hints[f.name], data[f.name]) for f in fields(cls) if f.name in data}
    try:
        return cls(**kwargs)
    except TypeError as exc:
        raise SettingsError(str(exc)) from exc


def _convert(tp: Any, value: Any) -> Any:
    origin, args = typing.get_origin(tp), typing.get_args(tp)
    if dataclasses.is_dataclass(tp):
        return _build(tp, value)
    if origin in (typing.Union, types.UnionType):  # X | None
        if value is None:
            return None
        return _convert(next(a for a in args if a is not type(None)), value)
    if origin is list:
        if not isinstance(value, list):
            raise SettingsError(f"Expected a list, got {value!r}")
        return [_convert(args[0], v) for v in value]
    if origin is dict:
        if not isinstance(value, dict):
            raise SettingsError(f"Expected an object, got {value!r}")
        return {str(k): _convert(args[1], v) for k, v in value.items()}
    return value


class Store:
    """Loads and atomically saves settings.json and state.json in the state directory."""

    def __init__(self, state_dir: Path):
        self.dir = Path(state_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.dir / "settings.json"
        self.state_path = self.dir / "state.json"

    @property
    def db_path(self) -> Path:
        return self.dir / "zigbee.db"

    @property
    def lock_path(self) -> Path:
        return self.dir / "radio.lock"

    def load_settings(self) -> Settings:
        if not self.settings_path.exists():
            return Settings()
        data = json.loads(self.settings_path.read_text())
        settings = Settings.from_dict(data)
        if data.get("version", 1) < SETTINGS_VERSION:
            backup = self.dir / f"settings.v{data.get('version', 1)}.json"
            if not backup.exists():
                _atomic_write(backup, data)
            self.save_settings(settings)
            LOGGER.info(
                "Migrated settings to version %d (old file kept as %s)",
                SETTINGS_VERSION,
                backup.name,
            )
        return settings

    def save_settings(self, settings: Settings) -> None:
        settings.validate()
        _atomic_write(self.settings_path, settings.to_dict())

    def load_state(self) -> State:
        if not self.state_path.exists():
            return State()
        return State.from_dict(json.loads(self.state_path.read_text()))

    def save_state(self, state: State) -> None:
        _atomic_write(self.state_path, state.to_dict())


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
