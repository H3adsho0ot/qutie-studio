"""Cross-check the raster reader against libcups's own (compressed) writer."""
import ctypes
import ctypes.util
import io
import os
import random
import struct

import pytest

from qutie import cupsraster

libcups = None
for name in (ctypes.util.find_library("cups"), "libcups.so.2"):
    if name:
        try:
            libcups = ctypes.CDLL(name)
            break
        except OSError:
            pass

pytestmark = pytest.mark.skipif(libcups is None, reason="libcups not installed")

WRITE_COMPRESSED = 2
HEADER_SIZE = 1796


def write_with_libcups(width, height, bits_per_color, bits_per_pixel, color_space, rows, num_colors=1):
    bytes_per_line = len(rows[0])
    header = bytearray(HEADER_SIZE)
    for off, val in ((372, width), (376, height), (384, bits_per_color), (388, bits_per_pixel),
                     (392, bytes_per_line), (400, color_space), (420, num_colors)):
        struct.pack_into("<I", header, off, val)
    read_fd, write_fd = os.pipe()
    libcups.cupsRasterOpen.restype = ctypes.c_void_p
    libcups.cupsRasterOpen.argtypes = [ctypes.c_int, ctypes.c_int]
    libcups.cupsRasterWriteHeader2.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    libcups.cupsRasterWritePixels.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint]
    libcups.cupsRasterClose.argtypes = [ctypes.c_void_p]
    ras = libcups.cupsRasterOpen(write_fd, WRITE_COMPRESSED)
    assert ras
    assert libcups.cupsRasterWriteHeader2(ras, bytes(header)) == 1
    for row in rows:
        assert libcups.cupsRasterWritePixels(ras, row, len(row)) == len(row)
    libcups.cupsRasterClose(ras)
    os.close(write_fd)
    with os.fdopen(read_fd, "rb") as f:
        return f.read()


def decode(data):
    (header, pixels), = cupsraster.read_pages(io.BytesIO(data))
    return header, pixels


def test_libcups_writes_compressed_stream_we_can_read():
    rng = random.Random(7)
    rows = []
    for i in range(60):
        kind = i % 5
        if kind == 0:
            rows.append(bytes(96))                                   # blank line (repeats)
        elif kind == 1:
            rows.append(bytes(rng.randrange(256) for _ in range(96)))  # noise: literals
        elif kind == 2:
            rows.append(bytes([255] * 40 + [0] * 56))                # two long runs
        elif kind == 3:
            rows.append(bytes([i, i, i, 7, 7, 1, 2, 3] * 12))        # mixed runs/literals
        else:
            rows.append(rows[-1])                                    # exact duplicate of previous line
    data = write_with_libcups(96, len(rows), 8, 8, 0, rows)
    assert data[:4] == b"2SaR"
    header, pixels = decode(data)
    assert (header.width, header.height, header.bytes_per_line) == (96, 60, 96)
    assert pixels == b"".join(rows)


def test_libcups_rgb_and_one_bit():
    rows = [bytes([i % 7, 0, 255] * 32) for i in range(10)]
    _, pixels = decode(write_with_libcups(32, 10, 8, 24, 1, rows, num_colors=3))
    assert pixels == b"".join(rows)
    rows = [bytes([0xF0, 0x0F] * 6) if i % 2 else bytes(12) for i in range(9)]
    _, pixels = decode(write_with_libcups(96, 9, 1, 1, 3, rows))
    assert pixels == b"".join(rows)
