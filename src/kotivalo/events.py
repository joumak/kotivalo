"""Domain events from devices, independent of the radio library.

zigbee.EventBridge turns zigpy's callbacks into these and puts them on a queue;
the service consumes them in one place (Service._consume_events).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LightReport:
    """A lamp reported one of its attributes (on_off, current_level, color_temperature)."""

    ieee: str
    attribute: str
    value: object


@dataclass(frozen=True)
class Announce:
    """A device announced itself, e.g. a lamp that just got mains power back."""

    ieee: str


@dataclass(frozen=True)
class Motion:
    """A motion sensor reported the room occupied or empty (or answered a poll)."""

    ieee: str
    occupied: bool
    polled: bool = False


@dataclass(frozen=True)
class Lux:
    ieee: str
    lux: float


@dataclass(frozen=True)
class Brightness:
    """A sensor that only tells bright from dim (the SNZB-06P), measured as it detects someone."""

    ieee: str
    bright: bool


@dataclass(frozen=True)
class Battery:
    ieee: str
    percent: float


@dataclass(frozen=True)
class Seen:
    """Any frame from a device: a sleepy one is awake right now (a chance to configure it)."""

    ieee: str


@dataclass(frozen=True)
class Button:
    """A remote's button: one of remotes.ACTIONS."""

    ieee: str
    action: str


Event = LightReport | Announce | Motion | Lux | Brightness | Battery | Seen | Button
