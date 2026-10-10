"""Remote button decoding, with frames as IKEA remotes send them."""

from kotivalo.remotes import LEVEL, ON_OFF, SCENES, Decoder, decode, parse_command

REMOTE = "aa:bb:cc:dd:ee:ff:00:11"
STYRBAR = "Remote Control N2"
IKEA = b"\x7c\x11"  # manufacturer code 0x117C, little-endian


def frame(sequence: int, command: int, payload: bytes = b"", manufacturer: bool = False) -> bytes:
    control = 0x05 if manufacturer else 0x01  # cluster-specific, client to server
    return bytes([control]) + (IKEA if manufacturer else b"") + bytes([sequence, command]) + payload


def test_parse_skips_reports_responses_and_short_frames():
    assert parse_command(frame(7, 0x01)) == (7, 0x01, b"")
    assert parse_command(frame(7, 0x07, b"\x01\x01", manufacturer=True)) == (7, 0x07, b"\x01\x01")
    assert parse_command(b"\x18\x07\x0a\x00\x00\x10\x01") is None  # global report
    assert parse_command(b"\x09\x07\x00") is None  # server to client
    assert parse_command(b"\x01\x07") is None


def test_on_off_and_dimming():
    assert decode(ON_OFF, 0x01, b"") == "on"
    assert decode(ON_OFF, 0x00, b"") == "off"
    assert decode(ON_OFF, 0x02, b"") == "toggle"
    assert decode(LEVEL, 0x05, b"\x00\x53") == "brighter_hold"  # move_with_on_off up
    assert decode(LEVEL, 0x01, b"\x01\x53") == "dimmer_hold"  # move down
    assert decode(LEVEL, 0x07, b"") == "dim_stop"
    assert decode(LEVEL, 0x03, b"\x00\x00") == "dim_stop"
    assert decode(LEVEL, 0x06, b"\x00\x2b\x05\x00") == "brighter"  # E1810 tap
    assert decode(LEVEL, 0x02, b"\x01\x2b\x05\x00") == "dimmer"


def test_arrows():
    assert decode(SCENES, 0x07, b"\x01\x01\x0d\x00") == "warmer"  # left
    assert decode(SCENES, 0x07, b"\x00\x01\x0d\x00") == "cooler"  # right
    assert decode(SCENES, 0x07, b"\x0d\x00\x00\x00") is None  # E1810 centre held
    assert decode(SCENES, 0x08, b"\x01\x0d\x00\x00") == "warmer_hold"
    assert decode(SCENES, 0x08, b"\x00\x0d\x00\x00") == "cooler_hold"
    assert decode(SCENES, 0x09, b"\x2c\x01") == "arrow_stop"


def test_duplicates_are_dropped_but_the_same_sequence_later_is_a_new_press():
    d = Decoder()
    assert d.decode(REMOTE, None, 1, ON_OFF, frame(5, 0x01), now=0.0) == "on"
    assert d.decode(REMOTE, None, 1, ON_OFF, frame(5, 0x01), now=0.5) is None
    assert d.duplicate
    assert d.decode(REMOTE, None, 1, ON_OFF, frame(6, 0x00), now=0.6) == "off"
    assert not d.duplicate
    assert d.decode(REMOTE, None, 1, ON_OFF, frame(5, 0x01), now=10.0) == "on"  # wrapped around


def test_styrbar_stray_on_after_an_arrow_is_ignored():
    d = Decoder()
    release = frame(1, 0x09, b"\x2c\x01", manufacturer=True)
    assert d.decode(REMOTE, STYRBAR, 1, SCENES, release, now=0.0) == "arrow_stop"
    assert d.decode(REMOTE, STYRBAR, 1, ON_OFF, frame(2, 0x01), now=0.2) is None
    assert d.decode(REMOTE, STYRBAR, 1, ON_OFF, frame(3, 0x01), now=2.0) == "on"


def test_other_clusters_are_not_buttons():
    assert Decoder().decode(REMOTE, None, 1, 0x0300, frame(1, 0x0A), now=0) is None


def test_remotes_are_named_like_the_box():
    from kotivalo.settings import default_name

    assert default_name("Remote Control N2", REMOTE) == "STYRBAR 0011"
    assert default_name("FLOALT panel WS 60x60", REMOTE) == "FLOALT panel WS 60x60 0011"
