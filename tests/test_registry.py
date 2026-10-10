from types import SimpleNamespace

import pytest

from kotivalo.light import FakeLight, LightCaps, LightError
from kotivalo.registry import Discovered, Registry
from kotivalo.settings import MotionRule, RemoteBinding, Settings
from kotivalo.zigbee import classify

PANEL_1 = "50:32:5f:ff:fe:6e:e5:2c"
PANEL_2 = "d0:cf:5e:ff:fe:1f:a3:9e"
SENSOR = "11:22:33:44:55:66:77:88"
REMOTE = "99:88:77:66:55:44:33:22"


def make_registry():
    settings = Settings()
    lights = {}
    registry = Registry(settings, lambda ieee, ep: lights.setdefault(ieee, FakeLight()))
    return settings, registry


def test_sync_adds_devices_lamps_and_controllers():
    settings, registry = make_registry()
    changed = registry.sync(
        [
            Discovered(PANEL_1, "light", "FLOALT panel WS 60x60", "IKEA of Sweden", 1),
            Discovered(SENSOR, "motion", "VALLHORN Wireless Motion Sensor"),
        ]
    )
    assert changed
    assert settings.devices[PANEL_1].name == "FLOALT panel WS 60x60 e52c"
    assert settings.devices[SENSOR].kind == "motion"
    assert settings.lights[PANEL_1].caps.model == "FLOALT panel WS 60x60"
    assert SENSOR not in settings.lights
    assert registry.light_ieees() == [PANEL_1]
    assert registry.controller(PANEL_1).available
    assert registry.paired(PANEL_1)
    assert not registry.sync([Discovered(PANEL_1, "light", "FLOALT panel WS 60x60", None, 1)])


def test_sync_upgrades_a_device_whose_interview_finished():
    settings, registry = make_registry()
    registry.sync([Discovered(PANEL_2, "other")])  # joined, not interviewed yet
    assert registry.light_ieees() == []
    assert registry.sync([Discovered(PANEL_2, "light", "FLOALT", "IKEA", 1)])
    assert settings.devices[PANEL_2].kind == "light"
    assert registry.light_ieees() == [PANEL_2]


def test_user_names_survive_sync():
    settings, registry = make_registry()
    registry.sync([Discovered(PANEL_1, "light", "FLOALT", None, 1)])
    settings.devices[PANEL_1].name = "Olohuone"
    registry.sync([Discovered(PANEL_1, "light", "FLOALT", None, 1)])
    assert settings.devices[PANEL_1].name == "Olohuone"


def test_set_caps_reaches_the_controller():
    settings, registry = make_registry()
    registry.sync([Discovered(PANEL_1, "light", "FLOALT", None, 1)])
    caps = LightCaps("FLOALT", "IKEA", True, 250, 454)
    registry.set_caps(PANEL_1, caps)
    assert registry.controller(PANEL_1).caps == caps
    assert settings.lights[PANEL_1].caps == caps


def test_remove_cleans_every_reference():
    settings, registry = make_registry()
    registry.sync(
        [Discovered(PANEL_1, "light", endpoint=1), Discovered(PANEL_2, "light", endpoint=1)]
    )
    settings.wakeup.light = PANEL_1
    settings.motion = [MotionRule(sensor=SENSOR, lights=[PANEL_1, PANEL_2])]
    settings.remotes = [RemoteBinding(remote=REMOTE, lights=[PANEL_1])]

    registry.remove(PANEL_1)

    assert PANEL_1 not in settings.devices and PANEL_1 not in settings.lights
    assert settings.wakeup.light is None
    assert settings.motion[0].lights == [PANEL_2]
    assert settings.remotes[0].lights == []
    with pytest.raises(LightError):
        registry.controller(PANEL_1)

    registry.remove(SENSOR)
    assert settings.motion == []


def endpoint(ep_id, inputs=(), outputs=()):
    return SimpleNamespace(
        endpoint_id=ep_id,
        in_clusters={c: object() for c in inputs},
        out_clusters={c: object() for c in outputs},
    )


@pytest.mark.parametrize(
    ("endpoints", "expected"),
    [
        ({1: endpoint(1, inputs=[0x0006, 0x0008, 0x0300])}, ("light", 1)),
        (  # VALLHORN: OnOff client on ep 1, occupancy on ep 2
            {1: endpoint(1, inputs=[0x0001], outputs=[0x0006]), 2: endpoint(2, inputs=[0x0406])},
            ("motion", None),
        ),
        ({1: endpoint(1, inputs=[0x0001], outputs=[0x0006, 0x0008, 0x0005])}, ("remote", None)),
        ({1: endpoint(1, inputs=[0x0000])}, ("other", None)),
        ({}, ("other", None)),  # joined but not interviewed yet
    ],
)
def test_classify(endpoints, expected):
    device = SimpleNamespace(endpoints={0: endpoint(0), **endpoints})
    assert classify(device) == expected
