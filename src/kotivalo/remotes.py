"""IKEA remote buttons: the ZCL commands a remote sends, decoded into actions.

Pure: no radio, no clock of its own. The same few commands cover STYRBAR, RODRET and
the older TRÅDFRI remotes (E1743 on/off switch, E1810 5-button, E1812 shortcut):

    on / off / toggle              On/Off 0x01 / 0x00 / 0x02 (E1812 tap: on)
    hold up / down, release        Level move(_with_on_off) mode 0 / 1, then stop(_with_on_off)
    E1810 up / down tap            Level step(_with_on_off) mode 0 / 1
    arrows (STYRBAR, E1810)        IKEA Scenes 0x07 tap, 0x08 hold, 0x09 release

Actions are data; the UI names them. Arrows change warmth: left is warmer.
"""

from __future__ import annotations

ON_OFF = 0x0006
LEVEL = 0x0008
SCENES = 0x0005
BUTTON_CLUSTERS = (ON_OFF, LEVEL, SCENES)

ACTIONS = (
    "on",
    "off",
    "toggle",
    "brighter",
    "dimmer",
    "brighter_hold",
    "dimmer_hold",
    "dim_stop",
    "warmer",
    "cooler",
    "warmer_hold",
    "cooler_hold",
    "arrow_stop",
)

# Zigbee model ids of IKEA remotes, and the names on the box.
PRODUCT_NAMES = {
    "Remote Control N2": "STYRBAR",
    "RODRET Dimmer": "RODRET",
    "RODRET wireless dimmer": "RODRET",
    "TRADFRI on/off switch": "TRÅDFRI on/off switch",
    "TRADFRI remote control": "TRÅDFRI remote",
    "TRADFRI SHORTCUT Button": "TRÅDFRI shortcut button",
}
STYRBAR_MODELS = {"Remote Control N2"}

DUPLICATE_S = 2.0  # a frame repeated by the network within this is the same press
STYRBAR_ON_AFTER_ARROW_S = 0.7  # STYRBAR sends a stray "on" after an arrow is released


def parse_command(data: bytes) -> tuple[int, int, bytes] | None:
    """(sequence number, command id, payload) of a cluster-specific command sent by a
    client (a remote). None for anything else: reports, responses, short frames."""
    if len(data) < 3:
        return None
    control = data[0]
    if control & 0x03 != 0x01:  # not a cluster-specific command
        return None
    if control & 0x08:  # server to client: a response, not a button
        return None
    start = 3 if control & 0x04 else 1  # skip a manufacturer code
    if len(data) < start + 2:
        return None
    return data[start], data[start + 1], bytes(data[start + 2 :])


def decode(cluster: int, command: int, payload: bytes) -> str | None:
    """The action of one command, or None if it is not a button we know."""
    if cluster == ON_OFF:
        return {0x00: "off", 0x40: "off", 0x01: "on", 0x42: "on", 0x02: "toggle"}.get(command)
    if cluster == LEVEL:
        up = payload[:1] == b"\x00"
        if command in (0x01, 0x05):  # move, move_with_on_off: held
            return "brighter_hold" if up else "dimmer_hold"
        if command in (0x02, 0x06):  # step, step_with_on_off: tapped
            return "brighter" if up else "dimmer"
        if command in (0x03, 0x07):  # stop, stop_with_on_off: released
            return "dim_stop"
        return None
    if cluster == SCENES:
        if command == 0x09:
            return "arrow_stop"
        if len(payload) < 2:
            return None
        value = int.from_bytes(payload[:2], "little")
        if command == 0x07:
            return {257: "warmer", 256: "cooler"}.get(value)  # 13: E1810 centre held
        if command == 0x08:
            return {3329: "warmer_hold", 3328: "cooler_hold"}.get(value)
    return None


class Decoder:
    """Decodes frames from many remotes, dropping network duplicates and STYRBAR's
    stray "on" after an arrow release."""

    def __init__(self) -> None:
        self._seen: dict[tuple, float] = {}
        self._arrow_released: dict[str, float] = {}
        self.duplicate = False  # whether the last frame decoded was a repeat

    def decode(
        self, ieee: str, model: str | None, endpoint: int, cluster: int, data: bytes, now: float
    ) -> str | None:
        self.duplicate = False
        if cluster not in BUTTON_CLUSTERS:
            return None
        parsed = parse_command(data)
        if parsed is None:
            return None
        sequence, command, payload = parsed
        self._seen = {k: t for k, t in self._seen.items() if now - t < DUPLICATE_S}
        key = (ieee, endpoint, cluster, sequence)
        if key in self._seen:
            self.duplicate = True
            return None
        self._seen[key] = now
        action = decode(cluster, command, payload)
        if action == "arrow_stop":
            self._arrow_released[ieee] = now
        elif action == "on" and model in STYRBAR_MODELS:
            if now - self._arrow_released.get(ieee, -1e9) < STYRBAR_ON_AFTER_ARROW_S:
                return None
        return action
