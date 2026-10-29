"""Wire protocol of the Qutie: pure functions that build and parse the bytes.

All command bytes below are the plain form; the transport XORs them with the
session key before sending (see transport.Session).
"""
import struct
from dataclasses import dataclass

HEAD_DOTS = 96      # printable width in dots (12 bytes per row)
DPMM = 8            # 203 dpi
CHUNK_BYTES = 720   # max raster bytes per block, rounded down to whole rows

GS = 0x1D
ESC = 0x1B


def handshake_request(r1: int, r2: int) -> bytes:
    return bytes([ESC, 0x1C]) + b"set mm" + bytes([r1, r2])


def session_key(r1: int, r2: int) -> int:
    return (r1 + r2) & 0xFF


def xor(data: bytes, key: int) -> bytes:
    return bytes(b ^ key for b in data)


CMD_STATUS = bytes([ESC, 0x12, 0x73])
CMD_INFO = bytes([ESC, 0x12, 0x64])
CMD_TEST_PAGE = bytes([ESC, ESC, 0x00])


def cmd_density(value: int) -> bytes:
    if not 0 <= value <= 255:
        raise ValueError("density must be 0..255")
    return bytes([GS]) + b"setc" + bytes([value])


def cmd_speed(value: int) -> bytes:
    if not 1 <= value <= 30:
        raise ValueError("speed must be 1..30")
    return bytes([GS]) + b"sets" + bytes([value])


def cmd_auto_off(seconds: int) -> bytes:
    if not 0 <= seconds <= 0xFFFF:
        raise ValueError("auto-off must be 0..65535 seconds")
    return bytes([GS]) + b"sett" + struct.pack("<H", seconds)


def cmd_feed_to_label(dots: int) -> bytes:
    if not 0 <= dots <= 0xFFFF:
        raise ValueError("label length must be 0..65535 dots")
    return bytes([GS, 0x66]) + struct.pack("<H", dots)


def cmd_feed(dots: int) -> bytes:
    if not 0 <= dots <= 0xFFFF:
        raise ValueError("feed must be 0..65535 dots")
    return bytes([ESC, ESC, 0x01]) + struct.pack("<H", dots)


def raster_block(compressed: bytes, width_bytes: int, rows: int) -> bytes:
    return (bytes([GS, 0x76, 0x30, 0x30]) + struct.pack("<HHI", width_bytes, rows, len(compressed))
            + compressed)


def split_rows(data: bytes, width_bytes: int) -> list[bytes]:
    """Split packed raster data into chunks of whole rows (at most CHUNK_BYTES each)."""
    per_chunk = max(1, CHUNK_BYTES // width_bytes) * width_bytes
    return [data[i:i + per_chunk] for i in range(0, len(data), per_chunk)]


# Status byte 0 is a bit field. Bit 4 (cover open) is confirmed on hardware; the others are
# the app's own mapping (out of paper, too hot, too cold, charge needed, battery damaged).
STATUS_FLAGS = {
    0x01: ("no-paper", "out of paper"),
    0x02: ("too-hot", "printer is too hot"),
    0x04: ("too-cold", "printer is too cold"),
    0x08: ("needs-charge", "battery needs charging"),
    0x10: ("cover-open", "paper cover is open"),
    0x20: ("battery-damaged", "battery is damaged"),
}
BLOCKING_FLAGS = 0x01 | 0x02 | 0x04 | 0x10 | 0x20   # printing is not possible with these set

# The printer volunteers "pooli_sta=<status byte 0>" whenever that byte changes; it can arrive
# in the middle of, or glued to, a query reply.
EVENT_PREFIX = b"pooli_sta="


def strip_events(data: bytes) -> tuple[bytes, list[int]]:
    """Remove status notifications from `data`; return (remaining bytes, status byte values in order)."""
    events, out, pos = [], bytearray(), 0
    while True:
        at = data.find(EVENT_PREFIX, pos)
        if at < 0 or at + len(EVENT_PREFIX) >= len(data):
            out += data[pos:]
            return bytes(out), events
        out += data[pos:at]
        events.append(data[at + len(EVENT_PREFIX)])
        pos = at + len(EVENT_PREFIX) + 1


def describe_flags(byte0: int) -> list[str]:
    return [desc for bit, (_, desc) in STATUS_FLAGS.items() if byte0 & bit]


@dataclass
class Status:
    battery: int
    auto_off_seconds: int
    flags: int = 0

    @property
    def problems(self) -> list[str]:
        return describe_flags(self.flags)

    @property
    def can_print(self) -> bool:
        return not self.flags & BLOCKING_FLAGS


@dataclass
class Info:
    model: str
    name: str
    serial: str
    firmware: str
    board: str
    bluetooth_name: str
    version: str


def parse_status(data: bytes) -> Status:
    data, _ = strip_events(data)
    if len(data) != 17 or not data.endswith(b"END"):
        raise ValueError(f"unexpected status reply ({len(data)} bytes)")
    return Status(battery=data[3], auto_off_seconds=struct.unpack_from("<H", data, 4)[0], flags=data[0])


def _text(data: bytes, start: int, length: int) -> str:
    return data[start:start + length].split(b"\0")[0].decode("latin1")


def parse_info(data: bytes) -> Info:
    data, _ = strip_events(data)
    if len(data) != 143 or not data.endswith(b"END"):
        raise ValueError(f"unexpected info reply ({len(data)} bytes)")
    return Info(
        model=_text(data, 0, 32),
        name=_text(data, 32, 24),
        serial=_text(data, 56, 32),
        firmware=".".join(str(b) for b in data[88:91]),
        board=".".join(str(b) for b in data[91:94]),
        bluetooth_name=_text(data, 94, 18),
        version=_text(data, 112, 12),
    )
