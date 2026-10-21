"""Startup must survive an unpowered mesh and must exit (never hang) when it fails."""

import socket

import pytest
import zigpy.exceptions
from zigpy_xbee.zigbee.application import ControllerApplication as XBeeApp

from kotivalo import app as app_module
from kotivalo import systemd, zigbee
from kotivalo.settings import RadioSettings, Store


class FakeRadioApp:
    """Just enough of a zigpy ControllerApplication for start_app()."""

    startup_error: BaseException | None = None

    def __init__(self):
        self.calls = []

    @classmethod
    async def new(cls, config, start_radio=True, **kwargs):
        assert start_radio is False  # start_app starts the radio itself
        return cls()

    async def startup(self, auto_form=False):
        self.calls.append("startup")
        self.auto_form = auto_form
        if self.startup_error is not None:
            raise self.startup_error

    async def shutdown(self, db=True):
        self.calls.append(f"shutdown(db={db})")

    async def permit(self, time_s=60, node=None):
        self.calls.append(f"broadcast {time_s}")
        raise zigpy.exceptions.DeliveryError("TXStatus.BROADCAST_RELAY_FAILURE")

    async def permit_ncp(self, time_s=60):
        self.calls.append(f"permit_ncp {time_s}")


class TolerantFake(zigbee.TolerantPermit, FakeRadioApp):
    pass


async def test_unrelayed_permit_broadcast_still_opens_the_coordinator():
    app = TolerantFake()
    await app.permit(0)
    assert app.calls == ["broadcast 0", "permit_ncp 0"]


def test_radio_class_gets_the_tolerant_permit():
    cls = zigbee.controller_class("xbee")
    assert issubclass(cls, XBeeApp)
    assert cls.permit is zigbee.TolerantPermit.permit


@pytest.mark.parametrize("radio_type", ["xbee", "ezsp", "znp"])
async def test_no_radio_forms_a_network_by_itself(monkeypatch, tmp_path, radio_type):
    """A new network would orphan every paired device: only `form-network` makes one."""
    created = []

    class App(FakeRadioApp):
        def __init__(self):
            super().__init__()
            created.append(self)

    monkeypatch.setattr(zigbee, "controller_class", lambda radio_type: App)
    await zigbee.start_app(RadioSettings(type=radio_type), tmp_path / "zigbee.db")
    assert created[0].auto_form is False


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (zigpy.exceptions.DeliveryError("relay failure"), zigbee.RadioError),
        (OSError("no such device"), zigbee.RadioError),
        (zigpy.exceptions.NetworkNotFormed("not formed"), zigbee.NetworkNotFormedError),
    ],
)
async def test_failed_startup_closes_the_database_and_raises(
    monkeypatch, tmp_path, error, expected
):
    created = []

    class App(FakeRadioApp):
        startup_error = error

        def __init__(self):
            super().__init__()
            created.append(self)

    monkeypatch.setattr(zigbee, "controller_class", lambda radio_type: App)
    with pytest.raises(expected):
        await zigbee.start_app(RadioSettings(), tmp_path / "zigbee.db")
    assert created[0].calls == ["startup", "shutdown(db=True)"]


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (RuntimeError("boom"), 1),
        (zigbee.RadioError("XStick unplugged"), 1),
        (zigbee.NetworkNotFormedError("run form-network"), app_module.EXIT_CONFIG),
    ],
)
async def test_serve_exits_on_any_startup_error(monkeypatch, tmp_path, error, code):
    stopped = []

    async def failing_start(self):
        raise error

    async def stop(self):
        stopped.append(True)

    monkeypatch.setattr(app_module.Service, "start", failing_start)
    monkeypatch.setattr(app_module.Service, "stop", stop)
    assert await app_module.serve(Store(tmp_path), host="127.0.0.1", port=0) == code
    assert stopped == [True]


def test_notify_reaches_systemd_socket(monkeypatch, tmp_path):
    path = tmp_path / "notify.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as server:
        server.bind(str(path))
        monkeypatch.setenv("NOTIFY_SOCKET", str(path))
        assert systemd.notify("READY=1")
        assert server.recv(64) == b"READY=1"


def test_notify_and_watchdog_are_noops_outside_systemd(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    monkeypatch.delenv("WATCHDOG_USEC", raising=False)
    assert systemd.notify("READY=1") is False
    assert systemd.watchdog_interval() is None


def test_watchdog_interval_is_half_of_watchdog_sec(monkeypatch):
    monkeypatch.setenv("WATCHDOG_USEC", "60000000")
    monkeypatch.delenv("WATCHDOG_PID", raising=False)
    assert systemd.watchdog_interval() == 30
    monkeypatch.setenv("WATCHDOG_PID", "1")  # someone else's watchdog
    assert systemd.watchdog_interval() is None
