import struct

import pytest

from qutie import protocol


def test_handshake_request():
    assert protocol.handshake_request(40, 87) == bytes.fromhex("1b1c736574206d6d2857")


def test_session_key_wraps():
    assert protocol.session_key(100, 100) == 200
    assert protocol.session_key(200 - 100, 200) == (300 & 0xFF)


def test_xor_roundtrip():
    data = bytes(range(256))
    assert protocol.xor(protocol.xor(data, 0x7F), 0x7F) == data


def test_simple_commands():
    assert protocol.CMD_STATUS == bytes.fromhex("1b1273")
    assert protocol.CMD_INFO == bytes.fromhex("1b1264")
    assert protocol.CMD_TEST_PAGE == bytes.fromhex("1b1b00")
    assert protocol.cmd_density(75) == b"\x1dsetc\x4b"
    assert protocol.cmd_speed(10) == b"\x1dsets\x0a"
    assert protocol.cmd_auto_off(900) == b"\x1dsett\x84\x03"
    assert protocol.cmd_feed_to_label(0x0130) == bytes.fromhex("1d663001")
    assert protocol.cmd_feed(112) == bytes.fromhex("1b1b017000")


def test_speed_out_of_range_is_rejected():
    with pytest.raises(ValueError):
        protocol.cmd_speed(35)  # the app's Qutie default is out of range and sends nothing


def test_raster_block_header():
    block = protocol.raster_block(b"\xaa\xbb", 12, 60)
    assert block[:4] == bytes.fromhex("1d763030")
    assert struct.unpack_from("<HHI", block, 4) == (12, 60, 2)
    assert block[12:] == b"\xaa\xbb"


def test_split_rows_whole_rows():
    data = bytes(12 * 130)
    chunks = protocol.split_rows(data, 12)
    assert [len(c) for c in chunks] == [720, 720, 120]
    assert all(len(c) % 12 == 0 for c in chunks)


def test_parse_status():
    raw = bytes.fromhex("0000016484034b00000000001800454e44")
    st = protocol.parse_status(raw)
    assert st.battery == 100
    assert st.auto_off_seconds == 900
    with pytest.raises(ValueError):
        protocol.parse_status(raw[:-1])


def test_parse_info():
    raw = bytearray(143)
    raw[0:7] = b"HPRT Q2"
    raw[32:37] = b"Qutie"
    raw[56:68] = b"SERIAL000001"
    raw[88:94] = bytes([1, 1, 22, 2, 0, 0])
    raw[94:104] = b"Qutie-0000"
    raw[112:117] = b"V4110"
    raw[-3:] = b"END"
    info = protocol.parse_info(bytes(raw))
    assert (info.model, info.name, info.serial) == ("HPRT Q2", "Qutie", "SERIAL000001")
    assert (info.firmware, info.board, info.bluetooth_name, info.version) == ("1.1.22", "2.0.0", "Qutie-0000", "V4110")


STATUS_OK = bytes.fromhex("0000016484034b00000000001900454e44")


def test_strip_events_standalone_prefix_and_suffix():
    # Captured sequences: a notification glued before or after a status block, and several in a row.
    cases = [
        (bytes.fromhex("706f6f6c695f7374613d10") + STATUS_OK, [0x10]),
        (STATUS_OK + bytes.fromhex("706f6f6c695f7374613d10"), [0x10]),
        (bytes.fromhex("706f6f6c695f7374613d00") * 2 + STATUS_OK, [0x00, 0x00]),
        (STATUS_OK, []),
    ]
    for raw, events in cases:
        data, found = protocol.strip_events(raw)
        assert data == STATUS_OK and found == events


def test_strip_events_keeps_partial_prefix_at_end():
    data, events = protocol.strip_events(STATUS_OK + b"pooli_sta=")
    assert events == [] and data.startswith(STATUS_OK)


def test_parse_status_ignores_notifications_and_decodes_flags():
    raw = bytes.fromhex("706f6f6c695f7374613d10") + bytes.fromhex("1000016484034b00000000001900454e44")
    st = protocol.parse_status(raw)
    assert st.flags == 0x10 and st.problems == ["paper cover is open"] and not st.can_print
    assert protocol.parse_status(STATUS_OK).can_print


def test_flag_descriptions_and_blocking_set():
    assert protocol.describe_flags(0x08) == ["battery needs charging"]
    assert protocol.describe_flags(0x11) == ["out of paper", "paper cover is open"]
    assert protocol.parse_status(STATUS_OK[:0] + bytes([0x08]) + STATUS_OK[1:]).can_print   # charge-needed only warns
