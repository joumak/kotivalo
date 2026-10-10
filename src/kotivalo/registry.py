"""The devices the service knows, and one LightController per lamp.

Radio-agnostic: the zigbee module (or the fake mode) reports what it finds as
`Discovered` records; names, rooms and lamp settings live in Settings.

Two kinds of controllers:
- `controllers`: one per bulb (a Zigbee device): polled, configured, reporting.
- `fixtures`: one per fixture (a lamp made of several bulbs, e.g. its spots), whose
  FixtureLight sends every command to all its bulbs.
The lamps people see (`lamp_ids`) are the fixtures and the bulbs in none of them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from kotivalo.light import (
    FixtureLight,
    Light,
    LightCaps,
    LightController,
    LightError,
    combined_state,
    common_caps,
)
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
        self.controllers: dict[str, LightController] = {}  # bulbs
        self.fixtures: dict[str, LightController] = {}
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
        self.sync_controllers()
        return changed

    def sync_controllers(self) -> None:
        lamps = set(self.light_ieees())
        for ieee in lamps - self.controllers.keys():
            device = self.settings.devices[ieee]
            caps = self.settings.light_settings(ieee).caps
            self.controllers[ieee] = LightController(self.make_light(ieee, device.endpoint), caps)
        for ieee in self.controllers.keys() - lamps:
            del self.controllers[ieee]
        fixtures = set(self.fixture_ids())
        for fid in fixtures - self.fixtures.keys():
            light = FixtureLight(lambda fid=fid: [self.controllers[m] for m in self.members(fid)])
            self.fixtures[fid] = LightController(light)
        for fid in self.fixtures.keys() - fixtures:
            del self.fixtures[fid]
        for fid in fixtures:
            self.update_fixture(fid)

    def light_ieees(self) -> list[str]:
        """Every bulb (a Zigbee lamp device), in a fixture or not."""
        return [ieee for ieee, d in self.settings.devices.items() if d.kind == "light"]

    def fixture_ids(self) -> list[str]:
        return [ieee for ieee, d in self.settings.devices.items() if d.kind == "fixture"]

    def members(self, fixture: str) -> list[str]:
        device = self.settings.devices.get(fixture)
        members = device.members if device is not None else []
        return [m for m in members if m in self.controllers]

    def fixture_of(self, ieee: str) -> str | None:
        for fid, device in self.settings.devices.items():
            if device.kind == "fixture" and ieee in device.members:
                return fid
        return None

    def lamp_ids(self) -> list[str]:
        """The lamps people see and use: fixtures, and the bulbs in none."""
        members = {m for fid in self.fixture_ids() for m in self.settings.devices[fid].members}
        return [
            ieee
            for ieee, d in self.settings.devices.items()
            if (d.kind == "light" and ieee not in members) or d.kind == "fixture"
        ]

    def is_lamp(self, ieee: str | None) -> bool:
        return ieee is not None and ieee in self.lamp_ids()

    def controller(self, ieee: str) -> LightController:
        """A lamp's controller: a fixture's, or a bulb's."""
        controller = self.fixtures.get(ieee) or self.controllers.get(ieee)
        if controller is None:
            raise LightError(f"Unknown lamp {ieee}")
        return controller

    def update_fixture(self, fid: str) -> bool:
        """A fixture's state and capabilities from its bulbs; True if its state changed."""
        controller = self.fixtures[fid]
        bulbs = [self.controllers[m] for m in self.members(fid)]
        caps = common_caps([b.caps for b in bulbs])
        self.settings.light_settings(fid).caps = controller.caps = caps
        before = controller.state
        controller.state = combined_state([b.state for b in bulbs])
        reachable = [b.reachable for b in bulbs]
        controller.reachable = None if not bulbs or None in reachable else any(reachable)
        errors = [b.last_error for b in bulbs if b.last_error]
        controller.last_error = errors[0] if bulbs and len(errors) == len(bulbs) else None
        return before != controller.state

    def set_caps(self, ieee: str, caps: LightCaps) -> None:
        self.settings.light_settings(ieee).caps = caps
        if ieee in self.controllers:
            self.controllers[ieee].caps = caps

    def paired(self, ieee: str) -> bool:
        """Known to the radio (in its device database); says nothing about reachability.
        A fixture is paired when all its bulbs are."""
        if ieee in self.fixtures:
            members = self.members(ieee)
            return bool(members) and all(m in self.discovered for m in members)
        return ieee in self.discovered

    def remove(self, ieee: str) -> list[str]:
        """Forget a device and every reference to it in the settings. A bulb leaves its
        fixture, and a fixture left without bulbs goes too; its bulbs (if any) become
        lamps of their own again. Returns everything removed."""
        settings = self.settings
        removed = [ieee]
        fixture = self.fixture_of(ieee)
        if fixture is not None:
            settings.devices[fixture].members.remove(ieee)
            if not settings.devices[fixture].members:
                removed += self.remove(fixture)
        settings.devices.pop(ieee, None)
        settings.lights.pop(ieee, None)
        self.discovered.pop(ieee, None)
        if settings.wakeup.light == ieee:
            settings.wakeup.light = None
        settings.motion = [r for r in settings.motion if r.sensor != ieee]
        settings.remotes = [b for b in settings.remotes if b.remote != ieee]
        for rule in [*settings.motion, *settings.remotes]:
            rule.lights = [x for x in rule.lights if x != ieee]
        self.sync_controllers()
        return removed
