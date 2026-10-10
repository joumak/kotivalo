"""EventBridge, fed through zigpy's real packet pipeline with recorded ZCL bytes."""

import asyncio

import pytest
import zigpy.application
import zigpy.device
import zigpy.endpoint
import zigpy.types as t
from zigpy.zcl.clusters.general import LevelControl, OnOff
from zigpy.zcl.clusters.lighting import Color

from kotivalo.events import Announce, LightReport
from kotivalo.zigbee import EventBridge

LAMP = "d0:cf:5e:ff:fe:1f:a3:9e"
NWK = 0x15A4


class RadiolessApp(zigpy.application.ControllerApplication):
    """Just enough of a zigpy application to push packets through it."""

    async def connect(self): ...
    async def disconnect(self): ...
    async def start_network(self): ...
    async def force_remove(self, dev): ...
    async def add_endpoint(self, descriptor): ...
    async def send_packet(self, packet): ...
    async def permit_ncp(self, time_s=60): ...
    async def permit_with_link_key(self, node, link_key, time_s=60): ...
    async def write_network_info(self, *, network_info, node_info): ...
    async def load_network_info(self, *, load_devices=False): ...
    async def reset_network_info(self): ...
    async def _network_scan(self, *args, **kwargs): ...
    async def _packet_capture(self, *args, **kwargs): ...
    async def _packet_capture_change_channel(self, channel): ...
    async def _subscribe_to_multicast_group(self, *args, **kwargs): ...
    async def _unsubscribe_from_multicast_group(self, *args, **kwargs): ...


@pytest.fixture
async def app():
    app = RadiolessApp({"device": {"path": "/dev/null"}})
    device = app.add_device(t.EUI64.convert(LAMP), NWK)
    ep = device.add_endpoint(1)
    ep.profile_id = 0x0104
    for cluster in (OnOff, LevelControl, Color):
        ep.add_input_cluster(cluster.cluster_id)
    ep.status = zigpy.endpoint.Status.ZDO_INIT
    device.status = zigpy.device.Status.ENDPOINTS_INIT
    return app


def packet(cluster: int, data: str, profile: int = 0x0104, endpoint: int = 1) -> t.ZigbeePacket:
    return t.ZigbeePacket(
        src=t.AddrModeAddress(addr_mode=t.AddrMode.NWK, address=NWK),
        src_ep=endpoint,
        dst=t.AddrModeAddress(addr_mode=t.AddrMode.NWK, address=0x0000),
        dst_ep=endpoint,
        tsn=5,
        profile_id=profile,
        cluster_id=cluster,
        data=t.SerializableBytes(bytes.fromhex(data)),
        lqi=255,
        rssi=-50,
    )


# ZCL Report Attributes, server -> client: frame control 0x18, tsn, command 0x0a,
# then attribute id (little endian), type, value.
ON_OFF_REPORT = "18050a00001001"  # on_off (0x0000, bool) = 1
LEVEL_REPORT = "18060a00002080"  # current_level (0x0000, uint8) = 128
CT_REPORT = "18070a07002172 01"  # color_temperature (0x0007, uint16) = 0x0172 = 370 mired


async def drain(queue: asyncio.Queue) -> list:
    await asyncio.sleep(0)
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


async def test_lamp_reports_become_light_reports(app):
    queue = asyncio.Queue()
    bridge = EventBridge(queue)
    bridge.attach_all(app)
    bridge.attach_all(app)  # attaching twice must not double the events

    app.packet_received(packet(OnOff.cluster_id, ON_OFF_REPORT))
    app.packet_received(packet(LevelControl.cluster_id, LEVEL_REPORT))
    app.packet_received(packet(Color.cluster_id, CT_REPORT.replace(" ", "")))

    events = await drain(queue)
    assert [(e.attribute, int(e.value)) for e in events] == [
        ("on_off", 1),
        ("current_level", 128),
        ("color_temperature", 370),
    ]
    assert all(e == LightReport(LAMP, e.attribute, e.value) for e in events)


async def test_device_announce_becomes_announce(app):
    queue = asyncio.Queue()
    bridge = EventBridge(queue)
    app.add_listener(bridge)
    ieee = bytes(reversed(bytes.fromhex(LAMP.replace(":", "")))).hex()
    # ZDO Device_annce: tsn, nwk (LE), ieee (LE), capabilities
    app.packet_received(packet(0x0013, f"81a415{ieee}8e", profile=0, endpoint=0))
    assert Announce(LAMP) in await drain(queue)


async def test_a_failing_handler_never_breaks_zigpy(app):
    class Broken(asyncio.Queue):
        def put_nowait(self, item):
            raise RuntimeError("bug in our code")

    bridge = EventBridge(Broken())
    bridge.attach_all(app)
    app.add_listener(bridge)
    app.packet_received(packet(OnOff.cluster_id, ON_OFF_REPORT))  # must not raise


SENSOR = "11:22:33:44:55:66:77:88"
SENSOR_NWK = 0x2B2B


def sensor_packet(cluster: int, data: str, endpoint: int) -> t.ZigbeePacket:
    p = packet(cluster, data, endpoint=endpoint)
    return p.replace(src=t.AddrModeAddress(addr_mode=t.AddrMode.NWK, address=SENSOR_NWK))


@pytest.fixture
def vallhorn(app):
    """A VALLHORN-shaped sensor: battery + OnOff output on ep 1, occupancy on 2, lux on 3."""
    device = app.add_device(t.EUI64.convert(SENSOR), SENSOR_NWK)
    for ep_id, inputs, outputs in ((1, [0x0001], [0x0006]), (2, [0x0406], []), (3, [0x0400], [])):
        ep = device.add_endpoint(ep_id)
        ep.profile_id = 0x0104
        for cluster_id in inputs:
            ep.add_input_cluster(cluster_id)
        for cluster_id in outputs:
            ep.add_output_cluster(cluster_id)
        ep.status = zigpy.endpoint.Status.ZDO_INIT
    device.status = zigpy.device.Status.ENDPOINTS_INIT
    return app


async def test_motion_sensor_reports_become_events(vallhorn):
    from kotivalo.events import Battery, Lux, Motion

    queue = asyncio.Queue()
    EventBridge(queue).attach_all(vallhorn)
    vallhorn.packet_received(sensor_packet(0x0406, "18080a00001801", endpoint=2))  # occupied
    vallhorn.packet_received(sensor_packet(0x0400, "18090a000021b439", endpoint=3))  # 14772
    vallhorn.packet_received(sensor_packet(0x0001, "180a0a210020c8", endpoint=1))  # 200 = 100 %
    vallhorn.packet_received(sensor_packet(0x0406, "180b0a00001800", endpoint=2))  # empty
    events = await drain(queue)
    assert events == [
        Motion(SENSOR, True),
        Lux(SENSOR, 30.0),
        Battery(SENSOR, 100.0),
        Motion(SENSOR, False),
    ]


def test_illuminance_conversion():
    from kotivalo.zigbee import illuminance_to_lux

    assert illuminance_to_lux(0) == 0.0  # too dark to measure
    assert illuminance_to_lux(1) == 1.0
    assert illuminance_to_lux(14772) == 30.0


REMOTE = "99:88:77:66:55:44:33:22"
REMOTE_NWK = 0x3C3C


@pytest.fixture
def styrbar(app):
    """A STYRBAR as it describes itself: no Scenes cluster, though its arrows use it."""
    device = app.add_device(t.EUI64.convert(REMOTE), REMOTE_NWK)
    device.model, device.manufacturer = "Remote Control N2", "IKEA of Sweden"
    ep = device.add_endpoint(1)
    ep.profile_id = 0x0104
    for cluster_id in (0x0000, 0x0001, 0x0003, 0x0020, 0x1000):
        ep.add_input_cluster(cluster_id)
    for cluster_id in (0x0003, 0x0004, 0x0006, 0x0008, 0x0019, 0x1000):
        ep.add_output_cluster(cluster_id)
    ep.status = zigpy.endpoint.Status.ZDO_INIT
    device.status = zigpy.device.Status.ENDPOINTS_INIT
    return app


def remote_packet(cluster: int, data: str) -> t.ZigbeePacket:
    p = packet(cluster, data)
    return p.replace(src=t.AddrModeAddress(addr_mode=t.AddrMode.NWK, address=REMOTE_NWK))


async def test_remote_buttons_become_button_events(styrbar):
    from kotivalo.events import Button

    queue = asyncio.Queue()
    bridge = EventBridge(queue)
    styrbar.add_listener(bridge)
    styrbar.packet_received(remote_packet(0x0006, "011001"))  # on
    styrbar.packet_received(remote_packet(0x0006, "011001"))  # the same frame again
    styrbar.packet_received(remote_packet(0x0008, "0111050053"))  # hold up
    styrbar.packet_received(remote_packet(0x0008, "011207"))  # release
    styrbar.packet_received(remote_packet(0x0005, "057c11130701010d00"))  # left arrow
    styrbar.packet_received(remote_packet(0x0006, "18140a00001001"))  # a report: not a button
    buttons = [e for e in await drain(queue) if isinstance(e, Button)]
    assert [b.action for b in buttons] == ["on", "brighter_hold", "dim_stop", "warmer"]
    assert {b.ieee for b in buttons} == {REMOTE}


async def test_a_lamp_sending_commands_is_not_a_remote(app):
    from kotivalo.events import Button

    queue = asyncio.Queue()
    app.add_listener(EventBridge(queue))
    app.packet_received(packet(0x0006, "011501"))
    assert not [e for e in await drain(queue) if isinstance(e, Button)]
