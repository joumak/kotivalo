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


Event = LightReport | Announce
