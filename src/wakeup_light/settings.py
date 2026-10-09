"""Persisted configuration (settings.json) and runtime state (state.json)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from wakeup_light.light import LightCaps

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
RADIO_TYPES = ("xbee", "ezsp", "znp")


class SettingsError(ValueError):
    pass


@dataclass
class Alarm:
    enabled: bool = False
    time: str = "07:00"  # local wall-clock HH:MM

    def validate(self) -> None:
        if not TIME_RE.match(self.time):
            raise SettingsError(f"Alarm time must be HH:MM, got {self.time!r}")


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
class Settings:
    timezone: str = "Europe/Helsinki"
    alarms: list[Alarm] = field(default_factory=lambda: [Alarm() for _ in WEEKDAYS])
    ramp: RampSettings = field(default_factory=RampSettings)
    radio: RadioSettings = field(default_factory=RadioSettings)
    target_ieee: str | None = None
    caps: LightCaps | None = None
    web_token: str | None = None  # if set, the web API requires it

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def validate(self) -> None:
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise SettingsError(f"Unknown timezone {self.timezone!r}") from exc
        if len(self.alarms) != 7:
            raise SettingsError("Need exactly 7 alarms (Mon..Sun)")
        for alarm in self.alarms:
            alarm.validate()
        self.ramp.validate()
        self.radio.validate()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        settings = cls(
            timezone=data.get("timezone", cls.timezone),
            alarms=[_build(Alarm, a) for a in data.get("alarms", [{}] * 7)],
            ramp=_build(RampSettings, data.get("ramp", {})),
            radio=_build(RadioSettings, data.get("radio", {})),
            target_ieee=data.get("target_ieee"),
            caps=_build(LightCaps, data["caps"]) if data.get("caps") else None,
            web_token=data.get("web_token"),
        )
        settings.validate()
        return settings

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class State:
    """Small runtime facts that must survive a restart."""

    skipped: list[str] = field(default_factory=list)  # alarm keys (UTC ISO) skipped or stopped
    last_run: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> State:
        return _build(cls, data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _build(cls, data: dict[str, Any]):
    """Construct a dataclass from a dict, ignoring unknown keys."""
    if not isinstance(data, dict):
        raise SettingsError(f"Expected an object for {cls.__name__}")
    names = {f.name for f in fields(cls)}
    try:
        return cls(**{k: v for k, v in data.items() if k in names})
    except TypeError as exc:
        raise SettingsError(str(exc)) from exc


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
        return Settings.from_dict(json.loads(self.settings_path.read_text()))

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
