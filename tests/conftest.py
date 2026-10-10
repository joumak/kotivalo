"""Shared test setup."""

import pytest

from kotivalo import app, light


@pytest.fixture(autouse=True)
def quick_switch_off(monkeypatch):
    """The service's 1.2 s fade-out before off (and the pauses between commands) would
    make every service test wait; test_light and test_sunrise check the real sequence."""
    monkeypatch.setattr(app, "OFF_FADE_S", 0.0)
    monkeypatch.setattr(light, "PARK_PAUSE_S", 0.0)
