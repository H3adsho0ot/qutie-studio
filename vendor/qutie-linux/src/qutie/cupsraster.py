"""Reader for CUPS raster streams (RaSt, RaS2, RaS3, either byte order)."""
import struct
from dataclasses import dataclass

# Sync word as it appears on disk -> (byte order, header size, run-length compressed)
_SYNC = {
    b"RaSt": (">", 420, False), b"tSaR": ("<", 420, False),
    b"RaS2": (">", 1796, True), b"2SaR": ("<", 1796, True),
    b"RaS3": (">", 1796, False), b"3SaR": ("<", 1796, False),
}

# cups_cspace_t values that matter here
CSPACE_W, CSPACE_RGB, CSPACE_K, CSPACE_SW, CSPACE_SRGB = 0, 1, 3, 18, 19


@dataclass
class PageHeader:
    width: int
    height: int
    bits_per_color: int
    bits_per_pixel: int
    bytes_per_line: int
    color_space: int
    num_copies: int
    media_type: str
    page_size: tuple[int, int]   # points


def _string(raw: bytes) -> str:
    return raw.split(b"\0")[0].decode("latin1")


def _parse_header(raw: bytes, order: str) -> PageHeader:
    u32 = lambda off: struct.unpack_from(order + "I", raw, off)[0]
    return PageHeader(
        width=u32(372), height=u32(376),
        bits_per_color=u32(384), bits_per_pixel=u32(388), bytes_per_line=u32(392),
        color_space=u32(400), num_copies=u32(340),
        media_type=_string(raw[128:192]), page_size=(u32(352), u32(356)),
    )


def _read_exact(stream, n: int) -> bytes:
    data = stream.read(n)
    if len(data) != n:
        raise EOFError("truncated CUPS raster stream")
    return data


def _read_rle(stream, h: PageHeader) -> bytes:
    bpp = max(1, (h.bits_per_pixel + 7) // 8)
    white = 0 if h.color_space == CSPACE_K else 0xFF
    out = bytearray()
    rows = 0
    while rows < h.height:
        repeat = _read_exact(stream, 1)[0] + 1
        line = bytearray()
        while len(line) < h.bytes_per_line:
            n = _read_exact(stream, 1)[0]
            if n == 128:                       # clear to end of line
                line += bytes([white]) * (h.bytes_per_line - len(line))
            elif n > 128:                      # literal run of 257 - n pixels
                line += _read_exact(stream, (257 - n) * bpp)
            else:                              # one pixel repeated n + 1 times
                line += _read_exact(stream, bpp) * (n + 1)
        line = bytes(line[:h.bytes_per_line])
        repeat = min(repeat, h.height - rows)
        out += line * repeat
        rows += repeat
    return bytes(out)


def read_pages(stream):
    """Yield (PageHeader, pixel bytes) for every page in a CUPS raster stream."""
    sync = stream.read(4)
    if not sync:
        return
    if sync not in _SYNC:
        raise ValueError("not a CUPS raster stream")
    order, header_size, compressed = _SYNC[sync]
    while True:
        raw = stream.read(header_size)
        if not raw:
            return
        if len(raw) != header_size:
            raise EOFError("truncated CUPS raster header")
        header = _parse_header(raw, order)
        if compressed:
            data = _read_rle(stream, header)
        else:
            data = _read_exact(stream, header.bytes_per_line * header.height)
        yield header, data
