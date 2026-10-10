"""The devices the service knows, and one LightController per lamp.

Radio-agnostic: the zigbee module (or the fake mode) reports what it finds as
`Discovered` records; names, rooms and lamp settings live in Settings.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from kotivalo.light import Light, LightCaps, LightController, LightError
from kotivalo.settings import Device, LightSettings, Settings, default_name

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Discovered:
    """What the radio knows about a device right now."""

    ieee: str
    kind: str  # light | motion | remote | other
    model: str | None = None
    manufacturer: str | None = None
    endpoint: int | None = None
    nwk: str | None = None
    last_seen: float | None = None  # unix time
    initialized: bool = True


class Registry:
    def __init__(self, settings: Settings, make_light: Callable[[str, int | None], Light | None]):
        self.settings = settings
        self.make_light = make_light
        self.controllers: dict[str, LightController] = {}
        self.discovered: dict[str, Discovered] = {}

    def sync(self, found: Iterable[Discovered]) -> bool:
        """Record devices reported by the radio. Returns True if settings changed."""
        changed = False
        for item in found:
            self.discovered[item.ieee] = item
            device = self.settings.devices.get(item.ieee)
            if device is None:
                self.settings.devices[item.ieee] = Device(
                    name=default_name(item.model, item.ieee),
                    kind=item.kind,
                    model=item.model,
                    manufacturer=item.manufacturer,
                    endpoint=item.endpoint,
                )
                LOGGER.info("New device %s: %s (%s)", item.ieee, item.model, item.kind)
                changed = True
            else:
                if item.model and device.name == default_name(None, item.ieee):
                    # joined before its interview: replace the placeholder name
                    device.name = default_name(item.model, item.ieee)
                    changed = True
                updates = {
                    "kind": item.kind if item.kind != "other" else device.kind,
                    "model": item.model or device.model,
                    "manufacturer": item.manufacturer or device.manufacturer,
                    "endpoint": item.endpoint if item.endpoint is not None else device.endpoint,
                }
                for attr, value in updates.items():
                    if getattr(device, attr) != value:
                        setattr(device, attr, value)
                        changed = True
            if item.kind == "light" and item.ieee not in self.settings.lights:
                self.settings.lights[item.ieee] = LightSettings(
                    caps=LightCaps(model=item.model, manufacturer=item.manufacturer)
                )
                changed = True
        self._sync_controllers()
        return changed

    def _sync_controllers(self) -> None:
        lamps = set(self.light_ieees())
        for ieee in lamps - self.controllers.keys():
            device = self.settings.devices[ieee]
            caps = self.settings.light_settings(ieee).caps
            self.controllers[ieee] = LightController(self.make_light(ieee, device.endpoint), caps)
        for ieee in self.controllers.keys() - lamps:
            del self.controllers[ieee]

    def light_ieees(self) -> list[str]:
        return [ieee for ieee, d in self.settings.devices.items() if d.kind == "light"]

    def controller(self, ieee: str) -> LightController:
        try:
            return self.controllers[ieee]
        except KeyError:
            raise LightError(f"Unknown lamp {ieee}") from None

    def set_caps(self, ieee: str, caps: LightCaps) -> None:
        self.settings.light_settings(ieee).caps = caps
        if ieee in self.controllers:
            self.controllers[ieee].caps = caps

    def paired(self, ieee: str) -> bool:
        """Known to the radio (in its device database); says nothing about reachability."""
        return ieee in self.discovered

    def remove(self, ieee: str) -> None:
        """Forget a device and every reference to it in the settings."""
        settings = self.settings
        settings.devices.pop(ieee, None)
        settings.lights.pop(ieee, None)
        self.discovered.pop(ieee, None)
        if settings.wakeup.light == ieee:
            settings.wakeup.light = None
        settings.motion = [r for r in settings.motion if r.sensor != ieee]
        settings.remotes = [b for b in settings.remotes if b.remote != ieee]
        for rule in [*settings.motion, *settings.remotes]:
            rule.lights = [x for x in rule.lights if x != ieee]
        self._sync_controllers()
