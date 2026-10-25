import json
from pathlib import Path

import pytest

from kotivalo.light import LightCaps
from kotivalo.settings import (
    FAKE_PREFIX,
    Alarm,
    Device,
    LightSettings,
    MotionRule,
    RemoteBinding,
    Settings,
    SettingsError,
    State,
    Store,
)

V1_FILE = Path(__file__).parent / "data" / "settings_v1.json"  # the Pi's real version 1 file
PANEL_1 = "50:32:5f:ff:fe:6e:e5:2c"
PANEL_2 = "d0:cf:5e:ff:fe:1f:a3:9e"


def test_round_trip(tmp_path):
    store = Store(tmp_path)
    settings = Settings()
    settings.devices[PANEL_1] = Device(name="Bedroom panel", room="Bedroom", kind="light")
    settings.lights[PANEL_1] = LightSettings(caps=LightCaps("FLOALT", "IKEA", True))
    settings.wakeup.light = PANEL_1
    settings.wakeup.alarms[0] = Alarm(enabled=True, time="06:45")
    settings.motion.append(MotionRule(sensor="aa:bb", lights=[PANEL_1]))
    settings.remotes.append(RemoteBinding(remote="cc:dd", lights=[PANEL_1]))
    settings.remotes.append(RemoteBinding(remote="ee:ff", master=True))
    store.save_settings(settings)
    assert store.load_settings() == settings

    store.save_state(State(skipped=["2026-10-12T04:00:00+00:00"]))
    assert store.load_state().skipped == ["2026-10-12T04:00:00+00:00"]


def test_defaults_when_missing(tmp_path):
    store = Store(tmp_path)
    assert store.load_settings() == Settings()
    assert store.load_state() == State()


def test_migrates_the_real_version_1_file_and_keeps_a_backup(tmp_path):
    original = V1_FILE.read_text()
    (tmp_path / "settings.json").write_text(original)
    store = Store(tmp_path)

    settings = store.load_settings()

    assert settings.version == 2
    assert settings.wakeup.light == PANEL_1
    assert settings.wakeup.ramp.duration_min == 30
    assert [a.time for a in settings.wakeup.alarms][5:] == ["08:00", "08:00"]
    assert settings.radio.channel == 25
    assert settings.devices[PANEL_1].kind == "light"
    assert settings.devices[PANEL_1].name == "FLOALT panel WS 60x60 e52c"
    assert settings.lights[PANEL_1].caps.max_mireds == 454
    assert settings.lights[PANEL_1].power_on == "previous"
    # The old file is kept untouched, and the new one is version 2 on disk.
    assert json.loads((tmp_path / "settings.v1.json").read_text()) == json.loads(original)
    assert json.loads((tmp_path / "settings.json").read_text())["version"] == 2
    assert store.load_settings() == settings  # loads again without migrating


def test_unknown_keys_are_ignored():
    data = Settings().to_dict()
    data["wakeup"]["ramp"]["future_option"] = 1
    data["something_new"] = True
    assert Settings.from_dict(data) == Settings()


def test_fake_devices_are_never_saved(tmp_path):
    store = Store(tmp_path)
    settings = Settings()
    fake = FAKE_PREFIX + "01"
    settings.devices[fake] = Device(name="Fake", kind="light")
    settings.devices[PANEL_2] = Device(name="Real", kind="light")
    settings.lights[fake] = LightSettings()
    settings.wakeup.light = fake
    settings.motion.append(MotionRule(sensor=fake, lights=[PANEL_2]))
    settings.remotes.append(RemoteBinding(remote="cc:dd", lights=[fake, PANEL_2]))
    store.save_settings(settings)

    saved = store.load_settings()
    assert list(saved.devices) == [PANEL_2]
    assert saved.lights == {}
    assert saved.wakeup.light is None
    assert saved.motion == []
    assert saved.remotes[0].lights == [PANEL_2]


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["wakeup"]["alarms"][0].update(time="7:00"),
        lambda d: d["wakeup"]["alarms"].pop(),
        lambda d: d["wakeup"]["ramp"].update(gamma=9),
        lambda d: d["wakeup"]["ramp"].update(warm_kelvin=5000, cool_kelvin=3000),
        lambda d: d["radio"].update(type="zigate"),
        lambda d: d.update(timezone="Mars/Olympus"),
        lambda d: d["night"].update(start="25:00"),
        lambda d: d["devices"].update({PANEL_1: {"kind": "toaster"}}),
        lambda d: d["lights"].update({PANEL_1: {"power_on": "maybe"}}),
        lambda d: d["motion"].extend(
            [{"sensor": "a", "lights": [PANEL_1]}, {"sensor": "b", "lights": [PANEL_1]}]
        ),
        lambda d: d["motion"].append({"sensor": "a", "night": {"level": 1}}),
        lambda d: d["remotes"].append({"remote": "a", "lights": [PANEL_1], "master": True}),
    ],
)
def test_invalid_settings_are_rejected(change):
    data = json.loads(json.dumps(Settings().to_dict()))
    change(data)
    with pytest.raises(SettingsError):
        Settings.from_dict(data)
