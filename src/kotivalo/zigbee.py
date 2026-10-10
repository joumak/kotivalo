"""zigpy glue: start the radio, find the light, send ZCL commands to it."""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import functools
import importlib
import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import zigpy.application
import zigpy.device
import zigpy.exceptions
import zigpy.types
from zigpy.zcl.clusters.general import LevelControl, OnOff, StartUpOnOff
from zigpy.zcl.clusters.lighting import Color, ColorCapabilities

from kotivalo.light import LightCaps, LightError, LightState
from kotivalo.settings import RadioSettings

LOGGER = logging.getLogger(__name__)

RADIO_MODULES = {
    "xbee": "zigpy_xbee.zigbee.application",
    "ezsp": "bellows.zigbee.application",
    "znp": "zigpy_znp.zigbee.application",
}
COMMAND_TIMEOUT_S = 8


class RadioError(Exception):
    pass


class NetworkNotFormedError(RadioError):
    """Needs a one-time `form-network`; restarting will not help."""


@contextlib.contextmanager
def radio_lock(path: Path) -> Iterator[None]:
    """Make sure only one process (the service or one CLI command) opens the radio."""
    with open(path, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RadioError(
                "The radio is in use (is the service running? "
                "stop it with: sudo systemctl stop kotivalo)"
            ) from None
        yield


def zigpy_config(radio: RadioSettings, db_path: Path) -> dict[str, Any]:
    device: dict[str, Any] = {"path": radio.path, "baudrate": radio.baudrate}
    if radio.flow_control:
        device["flow_control"] = radio.flow_control
    return {
        "device": device,
        "database_path": str(db_path),
        "network": {"channel": radio.channel},  # only used when forming
        "ota": {"enabled": False},
        "topology_scan_enabled": False,
    }


class TolerantPermit:
    """Mixin: permit-join works even when no router relays the broadcast.

    zigpy broadcasts Mgmt_Permit_Joining_req to all routers before opening the
    coordinator itself, and startup (which calls permit(0)) only tolerates
    MAC_CHANNEL_ACCESS_FAILURE. With every router unpowered (lamp switched off at
    the wall) the XBee reports BROADCAST_RELAY_FAILURE, and startup failed.
    """

    async def permit(self, time_s: int = 60, node=None) -> None:
        if node is not None:
            return await super().permit(time_s, node)
        try:
            await super().permit(time_s)
        except zigpy.exceptions.DeliveryError as exc:
            LOGGER.warning("Permit-join broadcast not relayed (no powered routers?): %s", exc)
            await self.permit_ncp(time_s)


@functools.cache
def controller_class(radio_type: str) -> type[zigpy.application.ControllerApplication]:
    try:
        module = importlib.import_module(RADIO_MODULES[radio_type])
    except ImportError as exc:
        raise RadioError(
            f"Radio library for {radio_type!r} is not installed (pip install -e '.[{radio_type}]')"
        ) from exc
    base = module.ControllerApplication
    return type(f"Tolerant{base.__name__}", (TolerantPermit, base), {})


async def start_app(
    radio: RadioSettings, db_path: Path, *, start_radio: bool = True
) -> zigpy.application.ControllerApplication:
    """Load the device database and (optionally) bring up the radio.

    XBee networks are formed explicitly with `form-network`, never automatically:
    every network write costs EM250 flash cycles and forces a re-pair.
    """
    cls = controller_class(radio.type)
    app = await cls.new(zigpy_config(radio, db_path), start_radio=False)
    if not start_radio:
        return app
    try:
        await app.startup(auto_form=radio.type != "xbee")
    except BaseException as exc:
        # zigpy's failed startup closes the radio but not the database, whose
        # worker thread would keep the process alive after the error.
        await app.shutdown()
        if isinstance(exc, zigpy.exceptions.NetworkNotFormed):
            raise NetworkNotFormedError(
                "The radio has no Zigbee network yet. Run: kotivalo form-network"
            ) from exc
        if isinstance(exc, Exception):
            raise RadioError(f"Cannot start the radio on {radio.path}: {exc!r}") from exc
        raise
    return app


def is_coordinator(device: zigpy.device.Device) -> bool:
    return device.nwk == 0x0000


def light_endpoint(device: zigpy.device.Device):
    """The first endpoint that has both On/Off and Level Control server clusters."""
    for ep_id, ep in device.endpoints.items():
        if ep_id == 0:
            continue
        clusters = getattr(ep, "in_clusters", {})
        if OnOff.cluster_id in clusters and LevelControl.cluster_id in clusters:
            return ep
    return None


def describe(device: zigpy.device.Device) -> dict[str, Any]:
    return {
        "ieee": str(device.ieee),
        "nwk": f"0x{device.nwk:04X}",
        "manufacturer": device.manufacturer,
        "model": device.model,
        "initialized": device.is_initialized,
        "is_light": light_endpoint(device) is not None,
        "last_seen": device.last_seen,
    }


def devices(app: zigpy.application.ControllerApplication) -> list[dict[str, Any]]:
    return [describe(d) for d in app.devices.values() if not is_coordinator(d)]


class DeviceEvents:
    """zigpy application listener that forwards the events we care about."""

    def __init__(self, callback: Callable[[str, Any], None]):
        self.callback = callback

    def device_joined(self, device) -> None:
        self.callback("joined", device)

    def device_initialized(self, device) -> None:
        self.callback("initialized", device)

    def device_left(self, device) -> None:
        self.callback("left", device)

    def device_removed(self, device) -> None:
        self.callback("removed", device)

    def connection_lost(self, exc) -> None:
        self.callback("connection_lost", exc)


class ZigbeeLight:
    """The Light protocol over zigpy ZCL commands."""

    def __init__(self, app: zigpy.application.ControllerApplication, ieee: str):
        self.app = app
        self.ieee = zigpy.types.EUI64.convert(ieee)

    def _endpoint(self):
        try:
            device = self.app.get_device(ieee=self.ieee)
        except KeyError:
            raise LightError(f"Device {self.ieee} is not paired") from None
        ep = light_endpoint(device)
        if ep is None:
            raise LightError(f"Device {self.ieee} has no dimmable light endpoint")
        return ep

    async def _send(self, what: str, action: Callable[[Any], Any]) -> Any:
        ep = self._endpoint()
        try:
            async with asyncio.timeout(COMMAND_TIMEOUT_S):
                return await action(ep)
        except (zigpy.exceptions.ZigbeeException, TimeoutError) as exc:
            raise LightError(f"{what} failed: {exc!r}") from exc

    async def set_level(self, level: int, transition_s: float = 0) -> None:
        tenths = max(0, round(transition_s * 10))
        await self._send(
            f"level {level}",
            lambda ep: ep.level.move_to_level_with_on_off(level=level, transition_time=tenths),
        )

    async def set_ct(self, mireds: int) -> None:
        await self._send(
            f"ct {mireds}",
            lambda ep: ep.light_color.move_to_color_temp(
                color_temp_mireds=mireds, transition_time=0
            ),
        )

    async def on(self) -> None:
        await self._send("on", lambda ep: ep.on_off.on())

    async def off(self) -> None:
        await self._send("off", lambda ep: ep.on_off.off())

    async def stop(self) -> None:
        await self._send("stop", lambda ep: ep.level.stop())

    async def read_state(self) -> LightState:
        async def read(ep):
            state = LightState()
            ok, _ = await ep.on_off.read_attributes(["on_off"], allow_cache=False)
            state.on = bool(ok["on_off"]) if "on_off" in ok else None
            ok, _ = await ep.level.read_attributes(["current_level"], allow_cache=False)
            state.level = ok.get("current_level")
            if Color.cluster_id in ep.in_clusters:
                ok, _ = await ep.light_color.read_attributes(
                    ["color_temperature"], allow_cache=False
                )
                state.mireds = ok.get("color_temperature")
            return state

        return await self._send("read state", read)

    async def read_caps(self) -> LightCaps:
        async def read(ep):
            caps = LightCaps(model=ep.device.model, manufacturer=ep.device.manufacturer)
            if Color.cluster_id in ep.in_clusters:
                ok, _ = await ep.light_color.read_attributes(
                    ["color_capabilities", "color_temp_physical_min", "color_temp_physical_max"],
                    allow_cache=False,
                )
                bits = ok.get("color_capabilities", 0)
                caps.supports_ct = bool(bits & ColorCapabilities.Color_temperature)
                caps.min_mireds = ok.get("color_temp_physical_min") or caps.min_mireds
                caps.max_mireds = ok.get("color_temp_physical_max") or caps.max_mireds
            return caps

        return await self._send("read capabilities", read)

    async def restore_after_power_loss(self) -> None:
        """Best effort: after a power cut, come back as before instead of full on."""
        try:
            await self._send(
                "write start_up_on_off",
                lambda ep: ep.on_off.write_attributes(
                    {"start_up_on_off": StartUpOnOff.PreviousValue}
                ),
            )
        except LightError as exc:
            LOGGER.info("Light does not accept start_up_on_off: %s", exc)
