"""LZO1X compression for raster blocks.

Uses the system liblzo2 when present; otherwise falls back to a literal-only
stream, which any LZO1X decoder accepts (larger, but valid).
"""
import ctypes
import ctypes.util

_WORK_BYTES = 16384 * 8
_lib = None
_lib_tried = False


def _load():
    global _lib, _lib_tried
    if _lib_tried:
        return _lib
    _lib_tried = True
    for name in (ctypes.util.find_library("lzo2"), "liblzo2.so.2"):
        if not name:
            continue
        try:
            _lib = ctypes.CDLL(name)
            return _lib
        except OSError:
            continue
    return None


def literal_only(data: bytes) -> bytes:
    n = len(data)
    if n <= 238:
        head = bytes([17 + n])
    else:
        extra = n - 3 - 15
        head = b"\x00" + b"\x00" * (extra // 255) + bytes([extra % 255])
    return head + data + b"\x11\x00\x00"


def compress(data: bytes) -> bytes:
    lib = _load()
    if lib is None:
        return literal_only(data)
    out = ctypes.create_string_buffer(len(data) + len(data) // 16 + 64 + 3)
    out_len = ctypes.c_size_t(len(out))
    work = ctypes.create_string_buffer(_WORK_BYTES)
    rc = lib.lzo1x_1_compress(data, ctypes.c_size_t(len(data)), out, ctypes.byref(out_len), work)
    if rc != 0:
        return literal_only(data)
    return out.raw[:out_len.value]


def decompress(data: bytes, max_len: int) -> bytes:
    """Reference decoder (liblzo2 only); used by the tests."""
    lib = _load()
    if lib is None:
        raise RuntimeError("liblzo2 not available")
    out = ctypes.create_string_buffer(max_len)
    out_len = ctypes.c_size_t(max_len)
    rc = lib.lzo1x_decompress_safe(data, ctypes.c_size_t(len(data)), out, ctypes.byref(out_len), None)
    if rc != 0:
        raise ValueError(f"lzo decompress failed ({rc})")
    return out.raw[:out_len.value]
