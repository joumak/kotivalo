"""Talk to an XBee directly with API AT-command frames (stdlib only, no zigpy).

Used for the one-time switch to the settings zigpy-xbee needs (AP=2, 57600 baud)
and for read-only diagnostics. Request frames are built so that no byte after the
start delimiter needs escaping, which makes them valid in both AP=1 and AP=2 mode.
"""

from __future__ import annotations

import os
import select
import termios
import time
from dataclasses import dataclass

START, ESCAPE = 0x7E, 0x7D
SPECIAL = {0x7E, 0x7D, 0x11, 0x13}
FRAME_AT = 0x08
FRAME_AT_RESPONSE = 0x88

# XBee BD parameter value -> baud rate
BD_RATES = {3: 9600, 4: 19200, 5: 38400, 6: 57600, 7: 115200}
TARGET_AP = 2
TARGET_BD = 6

INFO_COMMANDS = [
    "VR",
    "HV",
    "AP",
    "BD",
    "AI",
    "CH",
    "OI",
    "OP",
    "ID",
    "MY",
    "ZS",
    "EE",
    "EO",
    "NJ",
    "PL",
    "SH",
    "SL",
]


class XBeeError(Exception):
    pass


@dataclass
class AtResponse:
    command: str
    status: int  # 0 OK, 1 error, 2 invalid command, 3 invalid parameter
    value: bytes

    @property
    def ok(self) -> bool:
        return self.status == 0

    def as_int(self) -> int:
        return int.from_bytes(self.value, "big")


def build_at_frame(command: str, param: bytes = b"") -> tuple[int, bytes]:
    """Return (frame_id, frame) with a frame id chosen so nothing needs escaping."""
    for frame_id in range(1, 256):
        data = bytes([FRAME_AT, frame_id]) + command.encode() + param
        checksum = 0xFF - (sum(data) & 0xFF)
        body = len(data).to_bytes(2, "big") + data + bytes([checksum])
        if not SPECIAL.intersection(body):
            return frame_id, bytes([START]) + body
    raise XBeeError(f"AT{command} {param.hex()} cannot be sent without escaping")


def _unescape(raw: bytes) -> bytes:
    out = bytearray()
    it = iter(raw)
    for b in it:
        out.append((next(it, 0) ^ 0x20) if b == ESCAPE else b)
    return bytes(out)


def parse_frames(buf: bytes) -> list[bytes]:
    """Extract checksum-valid frame payloads. Tries both unescaped (AP=1) and escaped (AP=2).

    Every 0x7E is tried as a frame start: in AP=1 mode the payload itself may contain 0x7E.
    """
    frames = []
    for i, byte in enumerate(buf):
        if byte != START:
            continue
        chunk = buf[i + 1 :]
        for candidate in (chunk, _unescape(chunk)):
            if len(candidate) < 3:
                continue
            length = int.from_bytes(candidate[:2], "big")
            payload = candidate[2 : 2 + length]
            if len(payload) != length or len(candidate) < 3 + length:
                continue
            if (sum(payload) + candidate[2 + length]) & 0xFF == 0xFF:
                frames.append(payload)
                break
    return frames


class XBeePort:
    """A raw serial connection to the XBee at a fixed baud rate."""

    def __init__(self, path: str, baudrate: int):
        speed = getattr(termios, f"B{baudrate}")
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attrs = termios.tcgetattr(self.fd)
        attrs[0] = 0  # iflag: no XON/XOFF, no translation
        attrs[1] = 0  # oflag
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[3] = 0  # lflag: raw
        attrs[4] = attrs[5] = speed
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        termios.tcflush(self.fd, termios.TCIOFLUSH)
        self.baudrate = baudrate

    def close(self) -> None:
        os.close(self.fd)

    def __enter__(self) -> XBeePort:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def at(self, command: str, param: bytes = b"", timeout: float = 1.0) -> AtResponse | None:
        """Send one AT command and wait for its response; None on timeout."""
        frame_id, frame = build_at_frame(command, param)
        os.write(self.fd, frame)
        buf = b""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self.fd], [], [], 0.05)
            if ready:
                try:
                    buf += os.read(self.fd, 256)
                except BlockingIOError:
                    pass
            for payload in parse_frames(buf):
                if len(payload) >= 5 and payload[0] == FRAME_AT_RESPONSE and payload[1] == frame_id:
                    return AtResponse(payload[2:4].decode(), payload[4], payload[5:])
        return None


def _query(path: str, baudrate: int, command: str) -> AtResponse | None:
    with XBeePort(path, baudrate) as port:
        return port.at(command)


def find_baudrate(path: str, candidates=(57600, 9600, 115200, 38400, 19200)) -> int | None:
    for baudrate in candidates:
        if _query(path, baudrate, "VR"):
            return baudrate
    return None


def read_info(path: str, baudrate: int) -> dict[str, AtResponse | None]:
    with XBeePort(path, baudrate) as port:
        return {cmd: port.at(cmd) for cmd in INFO_COMMANDS}


def configure_for_zigpy(path: str, log=print) -> int:
    """Switch the XBee to AP=2 / 57600 baud and persist it. Returns the final baud rate.

    Nothing is written to flash until the new settings are verified to work, so a
    failure part-way leaves the persisted settings unchanged (replug to revert RAM).
    """
    target_rate = BD_RATES[TARGET_BD]
    current = find_baudrate(path)
    if current is None:
        raise XBeeError("XBee does not answer at any common baud rate. Replug it and retry.")

    with XBeePort(path, current) as port:
        ap, bd = port.at("AP"), port.at("BD")
        if not (ap and bd and ap.ok and bd.ok):
            raise XBeeError(f"Could not read AP/BD at {current} baud: {ap} {bd}")
        log(f"Found XBee at {current} baud: AP={ap.as_int()} BD={bd.as_int()}")
        if ap.as_int() == TARGET_AP and bd.as_int() == TARGET_BD and current == target_rate:
            log("Already configured; nothing to do.")
            return current

        rsp = port.at("AP", bytes([TARGET_AP]))
        if not (rsp and rsp.ok):
            raise XBeeError(f"Setting AP={TARGET_AP} failed: {rsp}")
        log(f"AP={TARGET_AP} set (not yet saved)")
        if current != target_rate:
            # The UART switches rate as the change is applied; the reply may be lost.
            port.at("BD", bytes([TARGET_BD]), timeout=0.5)
            time.sleep(0.5)

    with XBeePort(path, target_rate) as port:
        ap, bd = port.at("AP"), port.at("BD")
        if not (ap and bd and ap.as_int() == TARGET_AP and bd.as_int() == TARGET_BD):
            raise XBeeError(
                f"No valid answer at {target_rate} baud after the change ({ap}, {bd}). "
                "Nothing was saved: replug the XStick to restore the old settings."
            )
        log(f"Verified at {target_rate} baud: AP={ap.as_int()} BD={bd.as_int()}")

        # One WR only (the EM250 has limited flash write cycles); send nothing until it answers.
        rsp = port.at("WR", timeout=5)
        if not (rsp and rsp.ok):
            raise XBeeError(f"WR (save) failed: {rsp}")
        log("Saved to flash (WR)")

        rsp = port.at("FR")  # software reset, to prove the saved settings survive
        if not (rsp and rsp.ok):
            raise XBeeError(f"FR (reset) failed: {rsp}")
    time.sleep(3)

    with XBeePort(path, target_rate) as port:
        ap, bd = port.at("AP", timeout=3), port.at("BD")
        if not (ap and bd and ap.as_int() == TARGET_AP and bd.as_int() == TARGET_BD):
            raise XBeeError(f"After reset the saved settings did not stick: {ap}, {bd}")
    log(f"After reset: AP={TARGET_AP}, {target_rate} baud. Done.")
    return target_rate
