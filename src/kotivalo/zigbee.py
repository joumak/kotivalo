"""zigpy glue: start the radio, find the light, send ZCL commands to it."""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import functools
import importlib
import logging
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import zigpy.application
import zigpy.device
import zigpy.exceptions
import zigpy.types
from zigpy.zcl import foundation
from zigpy.zcl.clusters.general import Basic, LevelControl, OnOff, StartUpOnOff
from zigpy.zcl.clusters.lighting import Color, ColorCapabilities
from zigpy.zcl.helpers import ReportingConfig
from zigpy.zdo import types as zdo_types
from zigpy.zdo.types import Status as ZdoStatus

from kotivalo.events import Announce, Battery, Button, Event, LightReport, Lux, Motion, Seen
from kotivalo.light import LightCaps, LightError, LightState
from kotivalo.registry import Discovered
from kotivalo.remotes import BUTTON_CLUSTERS, Decoder
from kotivalo.settings import RadioSettings, channel_id

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
    radio: RadioSettings,
    db_path: Path,
    *,
    start_radio: bool = True,
    on_created: Callable[[zigpy.application.ControllerApplication], None] | None = None,
) -> zigpy.application.ControllerApplication:
    """Load the device database and (optionally) bring up the radio.

    `on_created` runs after the database is loaded and before the radio starts, so
    listeners attached there see every report from the first moment.

    Networks are formed explicitly with `form-network`, never automatically: a new
    network means re-pairing every device (and on the XBee, wears the EM250's flash).
    """
    cls = controller_class(radio.type)
    app = await cls.new(zigpy_config(radio, db_path), start_radio=False)
    if on_created is not None:
        on_created(app)
    if not start_radio:
        return app
    try:
        await app.startup(auto_form=False)
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


def radio_info(app: zigpy.application.ControllerApplication) -> dict[str, Any]:
    """What a started radio says about itself and its network."""
    node, net = app.state.node_info, app.state.network_info
    return {
        "manufacturer": node.manufacturer or None,
        "model": node.model or None,
        "firmware": node.version or None,
        "channel": net.channel or None,
        "pan_id": f"0x{net.pan_id:04X}",
    }


def is_coordinator(device: zigpy.device.Device) -> bool:
    return device.nwk == 0x0000


def light_endpoints(device: zigpy.device.Device) -> list:
    """Endpoints that switch a lamp, one per channel: those with both On/Off and Level
    Control server clusters, or, on a device with none, On/Off alone (a smart plug)."""
    switchable = [
        ep
        for ep_id, ep in sorted(device.endpoints.items())
        if ep_id != 0 and OnOff.cluster_id in getattr(ep, "in_clusters", {})
    ]
    dimmable = [ep for ep in switchable if LevelControl.cluster_id in ep.in_clusters]
    return dimmable or switchable


# (profile, device type) of lamps that only switch. Some list Level Control anyway:
# IKEA's TRETAKT plug (an On/Off Plug-in Unit) has it, but doesn't dim.
SWITCH_ONLY_TYPES = {
    (0x0104, 0x0100),  # Home Automation: On/Off Light
    (0x0104, 0x010A),  # On/Off Plug-in Unit
    (0x0104, 0x0009),  # Mains Power Outlet
    (0xC05E, 0x0000),  # ZLL: On/Off Light
    (0xC05E, 0x0010),  # On/Off Plug-in Unit
}


def is_dimmable(ep) -> bool:
    if (getattr(ep, "profile_id", None), getattr(ep, "device_type", None)) in SWITCH_ONLY_TYPES:
        return False
    return LevelControl.cluster_id in getattr(ep, "in_clusters", {})


def light_endpoint(device: zigpy.device.Device):
    """The first light endpoint: the device itself as a lamp."""
    endpoints = light_endpoints(device)
    return endpoints[0] if endpoints else None


OCCUPANCY_CLUSTER = 0x0406
ILLUMINANCE_CLUSTER = 0x0400
POWER_CLUSTER = 0x0001


def classify(device: zigpy.device.Device) -> tuple[str, int | None]:
    """(kind, light endpoint id): light, motion sensor, remote, or other."""
    ep = light_endpoint(device)
    if ep is not None:
        return "light", ep.endpoint_id
    endpoints = [e for i, e in device.endpoints.items() if i != 0]
    if any(OCCUPANCY_CLUSTER in getattr(e, "in_clusters", {}) for e in endpoints):
        return "motion", None
    if any(OnOff.cluster_id in getattr(e, "out_clusters", {}) for e in endpoints):
        return "remote", None
    return "other", None


def discovered(device: zigpy.device.Device) -> Discovered:
    kind, endpoint = classify(device)
    first = light_endpoint(device)
    return Discovered(
        ieee=str(device.ieee),
        kind=kind,
        model=device.model,
        manufacturer=device.manufacturer,
        endpoint=endpoint,
        nwk=f"0x{device.nwk:04X}",
        last_seen=device.last_seen,
        initialized=device.is_initialized,
        endpoints=tuple(ep.endpoint_id for ep in light_endpoints(device)),
        dimmable=first is None or is_dimmable(first),
    )


def discover(app: zigpy.application.ControllerApplication) -> list[Discovered]:
    return [discovered(d) for d in app.devices.values() if not is_coordinator(d)]


# Lamp attributes reported to the coordinator: (min s, max s, reportable change).
# The max interval doubles as a keep-alive; level reports at most every 2 s during fades.
LAMP_REPORTING = {
    OnOff.cluster_id: {"on_off": (0, 300, 1)},
    LevelControl.cluster_id: {"current_level": (2, 300, 5)},
    Color.cluster_id: {"color_temperature": (2, 600, 10)},
}
# Motion sensor attributes (VALLHORN: occupancy on ep 2, illuminance on ep 3, battery on
# ep 1). Occupancy reports at least every 5 min, so a silent sensor is noticed.
SENSOR_REPORTING = {
    OCCUPANCY_CLUSTER: {"occupancy": (0, 300, 1)},
    ILLUMINANCE_CLUSTER: {"measured_value": (10, 600, 500)},  # ~12 % change in lux
    POWER_CLUSTER: {"battery_percentage_remaining": (3600, 21600, 2)},
}
# Remotes: battery only (their buttons are commands, not attributes).
REMOTE_REPORTING = {POWER_CLUSTER: SENSOR_REPORTING[POWER_CLUSTER]}
CONFIGURE_TIMEOUT_S = 15
SLEEPY_TIMEOUT_S = 30  # a sleepy device answers only while awake
# A device that takes the bind but refuses a reporting setup with one of these reports
# changes on its own (Sonoff's SNZB-06P presence sensor): it is set up all the same.
REPORTS_ON_ITS_OWN = {
    foundation.Status.UNSUP_CLUSTER_COMMAND,
    foundation.Status.UNSUP_GENERAL_COMMAND,
}
ZDO_DEVICE_ANNOUNCE = 0x0013


async def configure_lamp(device: zigpy.device.Device, endpoint_id: int | None) -> bool:
    """Bind the lamp's on/off, level and colour clusters to the coordinator and ask for
    reports. Bindings are unicast to the coordinator (the XStick drops group traffic).
    Returns True when everything was accepted."""
    ep = device.endpoints.get(endpoint_id) if endpoint_id is not None else light_endpoint(device)
    if ep is None:
        return False
    clusters = [ep.in_clusters[c] for c in LAMP_REPORTING if c in ep.in_clusters]
    return await _configure(device, clusters, LAMP_REPORTING, CONFIGURE_TIMEOUT_S)


async def configure_sensor(device: zigpy.device.Device) -> bool:
    """Bind a motion sensor's occupancy, illuminance and battery to the coordinator and
    ask for reports. Its OnOff output (direct lamp control) is deliberately not bound.
    The sensor sleeps: call this while it is awake (right after joining or motion)."""
    clusters = [
        ep.in_clusters[c]
        for ep_id, ep in device.endpoints.items()
        if ep_id != 0
        for c in SENSOR_REPORTING
        if c in getattr(ep, "in_clusters", {})
    ]
    return bool(clusters) and await _configure(device, clusters, SENSOR_REPORTING, SLEEPY_TIMEOUT_S)


async def configure_remote(device: zigpy.device.Device) -> bool:
    """Bind a remote's button commands (On/Off, Level and IKEA's arrow Scenes) to the
    coordinator, so presses come to us instead of to a group, and ask for battery
    reports. Scenes is bound even when the descriptor doesn't list it (STYRBAR sends
    its arrows there anyway). The remote sleeps: call this while it is awake.
    Returns True when On/Off was bound."""
    app = device.application
    endpoint = next((e for i, e in device.endpoints.items() if i != 0), None)
    if endpoint is None:
        return False
    on_off_bound = False
    for cluster_id in BUTTON_CLUSTERS:
        target = zdo_types.MultiAddress()
        target.addrmode = 3
        target.ieee = app.state.node_info.ieee
        target.endpoint = app.get_endpoint_id(cluster_id, False)
        try:
            async with asyncio.timeout(SLEEPY_TIMEOUT_S):
                result = await device.zdo.Bind_req(
                    device.ieee, endpoint.endpoint_id, cluster_id, target
                )
        except (zigpy.exceptions.ZigbeeException, TimeoutError) as exc:
            LOGGER.warning(
                "Binding remote %s cluster 0x%04X failed: %r", device.ieee, cluster_id, exc
            )
            continue
        status = result[0] if result else None
        LOGGER.info("Remote %s cluster 0x%04X bind: %s", device.ieee, cluster_id, status)
        on_off_bound |= cluster_id == OnOff.cluster_id and status == ZdoStatus.SUCCESS
    battery = [
        e.in_clusters[POWER_CLUSTER]
        for i, e in device.endpoints.items()
        if i != 0 and POWER_CLUSTER in getattr(e, "in_clusters", {})
    ]
    if battery:
        await _configure(device, battery[:1], REMOTE_REPORTING, SLEEPY_TIMEOUT_S)
    await _log_firmware(device, endpoint)
    return on_off_bound


async def _log_firmware(device, endpoint) -> None:
    """IKEA's E1743 and E1810 bind only to groups before firmware 2.3.075: worth knowing
    when a remote's presses never arrive."""
    basic = getattr(endpoint, "in_clusters", {}).get(Basic.cluster_id)
    if basic is None:
        return
    try:
        async with asyncio.timeout(SLEEPY_TIMEOUT_S):
            ok, _ = await basic.read_attributes(["sw_build_id"], allow_cache=False)
    except (zigpy.exceptions.ZigbeeException, TimeoutError) as exc:
        LOGGER.info("Reading the firmware of %s failed: %r", device.ieee, exc)
        return
    LOGGER.info("Device %s %s firmware %s", device.ieee, device.model, ok.get("sw_build_id"))


async def _configure(device, clusters, reporting: dict, timeout_s: float) -> bool:
    ok = True
    for cluster in clusters:
        attributes = reporting[cluster.cluster_id]
        try:
            async with asyncio.timeout(timeout_s):
                bound = await cluster.bind()
                config = {
                    cluster.find_attribute(name): ReportingConfig(*values)
                    for name, values in attributes.items()
                }
                result = await cluster.configure_reporting_multiple(config)
        except (zigpy.exceptions.ZigbeeException, TimeoutError) as exc:
            LOGGER.warning("Configuring %s %s failed: %r", device.ieee, cluster.name, exc)
            ok = False
            continue
        bind_status = bound[0] if bound else None
        failed = {a.name: s for a, s in result.items() if s != foundation.Status.SUCCESS}
        on_its_own = bool(failed) and set(failed.values()) <= REPORTS_ON_ITS_OWN
        if bind_status == ZdoStatus.SUCCESS and on_its_own:
            LOGGER.info("Device %s %s: bound, reports on its own", device.ieee, cluster.name)
        elif bind_status != ZdoStatus.SUCCESS or failed:
            LOGGER.warning(
                "Device %s %s: bind %s, reporting not accepted for %s",
                device.ieee,
                cluster.name,
                bind_status,
                failed or "none",
            )
            ok = False
        else:
            LOGGER.info("Device %s %s: bound and reporting", device.ieee, cluster.name)
    return ok


# IKEA firmware image types of remotes, by model id (from IKEA's OTA index).
IKEA_IMAGE_TYPES = {
    "TRADFRI remote control": 0x11C1,  # E1810, "tradfri-controller"
    "TRADFRI wireless dimmer": 0x11C2,
    "TRADFRI on/off switch": 0x11C5,  # E1743, "tradfri-onoff-controller"
    "TRADFRI SHORTCUT Button": 0x11C6,  # E1812
    "Remote Control N2": 0x11CB,  # STYRBAR
    "RODRET Dimmer": 0x11CD,
}
WAKE_WINDOW_S = 300  # how long to keep trying to reach a sleeping remote
WAKE_RETRY_S = 1


class FirmwareError(Exception):
    pass


async def find_firmware(device: zigpy.device.Device):
    """IKEA's newest firmware for this remote, downloaded; None if IKEA has none."""
    from zigpy.ota import OtaImageWithMetadata
    from zigpy.ota.providers import Tradfri

    image_type = IKEA_IMAGE_TYPES.get(device.model or "")
    if image_type is None:
        raise FirmwareError(f"No IKEA firmware is known for {device.model!r}")
    index = await Tradfri().load_index() or []
    images = [i for i in index if i.image_type == image_type]
    if not images:
        return None
    newest = max(images, key=lambda i: i.file_version)
    return OtaImageWithMetadata(metadata=newest, firmware=await newest.fetch())


async def _ota_attempt(device, image, progress: Callable[[int, int], None]):
    """One offer: an image notify, then serve the device's requests until it finishes
    or goes quiet for 30 s. Only the notify is sent: no fast-poll requests, which would
    queue up behind a sleeping device and choke the XStick."""
    from zigpy.ota.manager import OTAManager

    with OTAManager(device, image, progress_callback=progress) as ota:
        await ota.notify()
        return await ota.wait()


async def update_firmware(
    device,
    image,
    on_progress: Callable[[float], None],
    wake_window_s: float = WAKE_WINDOW_S,
    attempt=_ota_attempt,
) -> str:
    """Send `image` to a sleepy device. It hears us only right after a button press, so
    keep offering the update until it starts (the user presses a button now and then).
    zigpy's own OTA handler would answer "no update available" to a query that falls
    between two offers, so it stays off (ota_in_progress) for the whole window.
    Returns "done", "none" (the device declined: up to date, or other hardware) or
    "failed". A failed update leaves the old firmware in place."""
    started = False

    def progress(current: int, total: int) -> None:
        nonlocal started
        started = True
        on_progress(100 * current / total if total else 0.0)

    loop = asyncio.get_running_loop()
    deadline = loop.time() + wake_window_s
    device.ota_in_progress = True
    try:
        while True:
            try:
                status = await attempt(device, image, progress)
            except (zigpy.exceptions.ZigbeeException, TimeoutError) as exc:
                status = exc
            if status == foundation.Status.SUCCESS:
                return "done"
            if status == foundation.Status.NO_IMAGE_AVAILABLE:
                return "none"
            if started or loop.time() >= deadline:
                LOGGER.warning("Firmware update of %s failed: %r", device.ieee, status)
                return "failed"
            LOGGER.info("Waiting for %s to ask for its firmware (%r)", device.ieee, status)
            await asyncio.sleep(WAKE_RETRY_S)
    finally:
        device.ota_in_progress = False


def illuminance_to_lux(measured_value: int) -> float:
    """ZCL illuminance is 10000 * log10(lux) + 1; 0 means too dark to measure."""
    return 0.0 if measured_value <= 0 else round(10 ** ((measured_value - 1) / 10000), 1)


class EventBridge:
    """Turns zigpy callbacks into domain events (events.py) on an asyncio queue.

    zigpy's emit() does not catch exceptions from callbacks, so every callback here
    is wrapped: a bug in our code must never break zigpy's packet handling.
    Attaching is idempotent per cluster object (a re-interview replaces them).
    """

    def __init__(self, queue: asyncio.Queue[Event]):
        self.queue = queue
        self._attached: set[int] = set()
        self._buttons = Decoder()
        self._lamps: dict[tuple[str, int], str] = {}  # (ieee, endpoint) -> lamp id

    def attach(self, device: zigpy.device.Device) -> None:
        kind, _ = classify(device)
        wanted = {"light": LAMP_REPORTING, "motion": SENSOR_REPORTING, "remote": REMOTE_REPORTING}
        wanted = wanted.get(kind, {})
        endpoints = [e for i, e in device.endpoints.items() if i != 0]
        if kind == "light":
            endpoints = light_endpoints(device)
            ieee = str(device.ieee)
            for i, ep in enumerate(endpoints):  # the first channel is the device itself
                lamp = ieee if i == 0 else channel_id(ieee, ep.endpoint_id)
                self._lamps[(ieee, ep.endpoint_id)] = lamp
        for ep in endpoints:
            for cluster_id in wanted:
                cluster = getattr(ep, "in_clusters", {}).get(cluster_id)
                if cluster is not None and id(cluster) not in self._attached:
                    self._attached.add(id(cluster))
                    cluster.on_event("attribute_report", self._on_report)

    def attach_all(self, app: zigpy.application.ControllerApplication) -> None:
        for device in app.devices.values():
            if not is_coordinator(device):
                self.attach(device)

    def _put(self, event: Event) -> None:
        try:
            self.queue.put_nowait(event)
        except Exception:  # noqa: BLE001 - never raise into zigpy
            LOGGER.exception("Dropping event %r", event)

    def _on_report(self, event) -> None:
        try:
            ieee, name, value = str(event.device_ieee), event.attribute_name, event.value
            if name in ("on_off", "current_level", "color_temperature"):
                lamp = self._lamps.get((ieee, event.endpoint_id), ieee)
                self._put(LightReport(lamp, name, value))
            elif name == "occupancy":
                self._put(Motion(ieee, bool(int(value) & 1)))
            elif name == "measured_value" and event.cluster_id == ILLUMINANCE_CLUSTER:
                self._put(Lux(ieee, illuminance_to_lux(int(value))))
            elif name == "battery_percentage_remaining" and int(value) != 0xFF:
                self._put(Battery(ieee, int(value) / 2))  # reported in half percents
        except Exception:  # noqa: BLE001
            LOGGER.exception("Bad attribute report %r", event)

    # zigpy application listener methods
    def handle_message(self, device, profile, cluster, src_ep, dst_ep, data) -> None:
        try:
            if is_coordinator(device):
                return
            ieee = str(device.ieee)
            self._put(Seen(ieee))
            if profile == 0 and cluster == ZDO_DEVICE_ANNOUNCE:
                self._put(Announce(ieee))
            elif cluster in BUTTON_CLUSTERS and classify(device)[0] == "remote":
                action = self._buttons.decode(
                    ieee, device.model, src_ep, cluster, bytes(data), time.monotonic()
                )
                if action is not None:
                    self._put(Button(ieee, action))
                elif not self._buttons.duplicate:  # a button we don't know yet
                    LOGGER.info("Remote %s 0x%04X %s: unknown button", ieee, cluster, data.hex())
        except Exception:  # noqa: BLE001
            LOGGER.exception("Bad message from %r", device)

    def device_initialized(self, device) -> None:
        try:
            self.attach(device)
        except Exception:  # noqa: BLE001
            LOGGER.exception("Attaching to %r failed", device)

    device_reinterviewed = device_initialized


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

    def __init__(
        self, app: zigpy.application.ControllerApplication, ieee: str, endpoint: int | None = None
    ):
        self.app = app
        self.ieee = zigpy.types.EUI64.convert(ieee)
        self.endpoint_id = endpoint

    def _endpoint(self):
        try:
            device = self.app.get_device(ieee=self.ieee)
        except KeyError:
            raise LightError(f"Device {self.ieee} is not paired") from None
        if self.endpoint_id is not None and self.endpoint_id in device.endpoints:
            return device.endpoints[self.endpoint_id]
        ep = light_endpoint(device)
        if ep is None:
            raise LightError(f"Device {self.ieee} has no light endpoint")
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

    async def fade(self, level: int, transition_s: float) -> None:
        tenths = max(0, round(transition_s * 10))
        await self._send(
            f"fade {level}",  # move_to_level without on/off: an off lamp stays off
            lambda ep: ep.level.move_to_level(level=level, transition_time=tenths),
        )

    async def move(self, up: bool, rate: int) -> None:
        """Dim until stop(). Up switches an off lamp on; down stops at the lowest level
        and never switches the lamp off."""
        if up:
            await self._send("move up", lambda ep: ep.level.move_with_on_off(0, rate))
        else:
            await self._send("move down", lambda ep: ep.level.move(1, rate))

    async def read_state(self) -> LightState:
        async def read(ep):
            state = LightState()
            ok, _ = await ep.on_off.read_attributes(["on_off"], allow_cache=False)
            state.on = bool(ok["on_off"]) if "on_off" in ok else None
            if is_dimmable(ep):
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
            caps = LightCaps(
                model=ep.device.model, manufacturer=ep.device.manufacturer, dimmable=is_dimmable(ep)
            )
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

    async def set_power_on(self, previous: bool) -> None:
        """What the lamp does when mains power returns: its previous state (a power cut
        at night keeps it off) or on (the wall switch works). Best effort."""
        value = StartUpOnOff.PreviousValue if previous else StartUpOnOff.On
        try:
            await self._send(
                "write start_up_on_off",
                lambda ep: ep.on_off.write_attributes({"start_up_on_off": value}),
            )
        except LightError as exc:
            LOGGER.info("Light does not accept start_up_on_off: %s", exc)
