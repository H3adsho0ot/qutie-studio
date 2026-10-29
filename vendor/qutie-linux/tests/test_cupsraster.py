import io

import pytest

from qutie import cupsraster
from cups_helpers import stream

ROWS = [bytes([0, 0, 255, 255, 255, 0, 0, 0, 7, 8, 9, 10]), bytes(12), bytes(12), bytes(range(12))]
PAGE = (96, 4, 8, 8, 0, ROWS)


@pytest.mark.parametrize("version", ["RaSt", "RaS2", "RaS3"])
@pytest.mark.parametrize("little", [True, False])
def test_roundtrip_all_versions_and_byte_orders(version, little):
    data = stream([PAGE, PAGE], version, little)
    pages = list(cupsraster.read_pages(io.BytesIO(data)))
    assert len(pages) == 2
    header, pixels = pages[0]
    assert (header.width, header.height, header.bits_per_pixel, header.bytes_per_line) == (96, 4, 8, 12)
    assert header.page_size == (34, 85) and header.media_type == "label"
    assert pixels == b"".join(ROWS)


def test_rgb_pixels_use_pixel_sized_runs():
    rows = [bytes([10, 20, 30] * 4 + [1, 2, 3, 4, 5, 6]), bytes(18)]
    data = stream([(6, 2, 8, 24, 1, rows)], "RaS2")
    (_, pixels), = cupsraster.read_pages(io.BytesIO(data))
    assert pixels == b"".join(rows)


def test_rejects_garbage_and_truncation():
    with pytest.raises(ValueError):
        list(cupsraster.read_pages(io.BytesIO(b"GARBAGE" * 10)))
    with pytest.raises(EOFError):
        list(cupsraster.read_pages(io.BytesIO(stream([PAGE], "RaS3")[:-5])))


def test_empty_stream_has_no_pages():
    assert list(cupsraster.read_pages(io.BytesIO(b""))) == []
