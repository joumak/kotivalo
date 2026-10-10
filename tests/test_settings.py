import json

import pytest

from kotivalo.light import LightCaps
from kotivalo.settings import Alarm, Settings, SettingsError, State, Store


def test_round_trip(tmp_path):
    store = Store(tmp_path)
    settings = Settings(target_ieee="50:32:5f:ff:fe:6e:e5:2c", caps=LightCaps("FLOALT", "IKEA"))
    settings.alarms[0] = Alarm(enabled=True, time="06:45")
    store.save_settings(settings)
    assert store.load_settings() == settings

    store.save_state(State(skipped=["2026-10-12T04:00:00+00:00"]))
    assert store.load_state().skipped == ["2026-10-12T04:00:00+00:00"]


def test_defaults_when_missing(tmp_path):
    store = Store(tmp_path)
    assert store.load_settings() == Settings()
    assert store.load_state() == State()


def test_unknown_keys_are_ignored(tmp_path):
    data = Settings().to_dict()
    data["ramp"]["future_option"] = 1
    data["something_new"] = True
    assert Settings.from_dict(data) == Settings()


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["alarms"][0].update(time="7:00"),
        lambda d: d["alarms"].pop(),
        lambda d: d["ramp"].update(gamma=9),
        lambda d: d["ramp"].update(warm_kelvin=5000, cool_kelvin=3000),
        lambda d: d["radio"].update(type="zigate"),
        lambda d: d.update(timezone="Mars/Olympus"),
    ],
)
def test_invalid_settings_are_rejected(change):
    data = json.loads(json.dumps(Settings().to_dict()))
    change(data)
    with pytest.raises(SettingsError):
        Settings.from_dict(data)
