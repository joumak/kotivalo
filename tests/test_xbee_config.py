from kotivalo.xbee_config import SPECIAL, START, build_at_frame, parse_frames


def response_frame(frame_id: int, command: str, value: bytes, escaped: bool) -> bytes:
    payload = bytes([0x88, frame_id]) + command.encode() + b"\x00" + value
    body = len(payload).to_bytes(2, "big") + payload + bytes([0xFF - (sum(payload) & 0xFF)])
    if escaped:
        body = b"".join(bytes([0x7D, b ^ 0x20]) if b in SPECIAL else bytes([b]) for b in body)
    return bytes([START]) + body


def test_request_frames_need_no_escaping():
    for command, param in [("VR", b""), ("AP", b"\x02"), ("BD", b"\x06"), ("WR", b"")]:
        _, frame = build_at_frame(command, param)
        assert frame[0] == START
        assert not SPECIAL.intersection(frame[1:])
        assert (sum(frame[3:]) & 0xFF) == 0xFF  # checksum over data + checksum byte


def test_known_frames_match_xbee_manual_values():
    assert build_at_frame("AP", b"\x02")[1].hex() == "7e000508014150" + "0263"
    assert build_at_frame("WR")[1].hex() == "7e0004080157524d"


def test_parse_unescaped_payload_containing_start_byte():
    value = bytes.fromhex("9114707ede98eda8")  # real OP value, contains 0x7E
    frames = parse_frames(b"\x00" + response_frame(5, "OP", value, escaped=False))
    assert frames[0][2:4] == b"OP"
    assert frames[0][5:] == value


def test_parse_escaped_frame():
    value = bytes.fromhex("117e7d13")
    frames = parse_frames(response_frame(9, "KY", value, escaped=True))
    assert frames[0][1] == 9
    assert frames[0][5:] == value


def test_parse_ignores_bad_checksum():
    frame = bytearray(response_frame(1, "VR", b"\x21\xa7", escaped=False))
    frame[-1] ^= 0xFF
    assert parse_frames(bytes(frame)) == []
