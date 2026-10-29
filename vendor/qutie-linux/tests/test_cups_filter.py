import io
import struct

import pytest
from PIL import Image

from qutie import cups_filter, cupsraster, lzo, protocol
from cups_helpers import stream


def gray_page(rows_pixels, width=96):
    rows = [bytes(r) for r in rows_pixels]
    return (width, len(rows), 8, 8, 0, rows)


def run(data, options=""):
    out = io.BytesIO()
    pages = cups_filter.run(io.BytesIO(data), out, cups_filter.parse_options(options), log=io.StringIO())
    return pages, out.getvalue()


def split_commands(out):
    """Return (density bytes, blocks [(w, h, raw)], feed bytes) from a one-page stream."""
    assert out[:5] == b"\x1dsetc"
    density, pos, blocks = out[5], 6, []
    while out[pos:pos + 4] == bytes.fromhex("1d763030"):
        w, h, n = struct.unpack_from("<HHI", out, pos + 4)
        raw = lzo.decompress(out[pos + 12:pos + 12 + n], w * h)
        blocks.append((w, h, raw))
        pos += 12 + n
    return density, blocks, out[pos:]


def test_parse_options():
    assert cups_filter.parse_options('QutieDensity=100 QutieMedia=Gap "title=a b" flag') == {
        "QutieDensity": "100", "QutieMedia": "Gap", "title": "a b", "flag": ""}


def test_black_pixels_become_one_bits_with_defaults():
    page = gray_page([[255] * 96, [0] * 96])
    pages, out = run(stream([page], "RaS2"))
    assert pages == 1
    density, blocks, feed = split_commands(out)
    assert density == 75
    assert blocks == [(12, 2, bytes(12) + b"\xff" * 12)]
    assert feed == protocol.cmd_feed(112)


def test_options_density_gap_and_feed():
    page = gray_page([[0] * 96] * 3)
    _, out = run(stream([page], "RaS3"), "QutieDensity=130 QutieMedia=Gap")
    density, _, feed = split_commands(out)
    assert density == 130 and feed == protocol.cmd_feed_to_label(3)
    _, out = run(stream([page], "RaS3"), "QutieFeed=4")
    assert split_commands(out)[2] == protocol.cmd_feed(32)


def test_one_bit_k_colorspace_black_is_one():
    row = bytes([0b10000000]) + bytes(11)         # first pixel black in K space
    page = (96, 1, 1, 1, cupsraster.CSPACE_K, [row])
    _, out = run(stream([page], "RaS2"))
    assert split_commands(out)[1] == [(12, 1, row)]


def test_one_bit_w_colorspace_zero_is_black():
    row = bytes([0b01111111]) + b"\xff" * 11       # first pixel black in W space (0 = black)
    page = (96, 1, 1, 1, cupsraster.CSPACE_W, [row])
    _, out = run(stream([page], "RaS2"))
    assert split_commands(out)[1] == [(12, 1, bytes([0b10000000]) + bytes(11))]


def test_rgb_page_and_multiple_pages():
    rgb = (96, 1, 8, 24, cupsraster.CSPACE_SRGB, [bytes([0, 0, 0]) * 96])
    pages, out = run(stream([rgb, rgb], "RaS2"))
    assert pages == 2 and out.count(b"\x1dsetc") == 2


def test_long_label_is_chunked():
    page = gray_page([[0] * 96] * 130)
    _, out = run(stream([page], "RaS2"))
    assert [(w, h) for w, h, _ in split_commands(out)[1]] == [(12, 60), (12, 60), (12, 10)]


def test_unsupported_format_is_an_error():
    bad = (96, 1, 16, 16, 0, [bytes(192)])
    with pytest.raises(ValueError):
        run(stream([bad], "RaS3"))


def test_main_usage_and_errors(tmp_path, capsys):
    assert cups_filter.main(["f"]) == 1
    junk = tmp_path / "x.ras"
    junk.write_bytes(b"not raster data")
    assert cups_filter.main(["f", "1", "u", "t", "1", "", str(junk)]) == 1


def test_wide_page_warns_and_scales():
    page = gray_page([[0] * 192] * 4, width=192)
    log = io.StringIO()
    out = io.BytesIO()
    cups_filter.run(io.BytesIO(stream([page], "RaS3")), out, {}, log=log)
    assert "WARNING: page is 192 dots wide" in log.getvalue()
    assert split_commands(out.getvalue())[1][0][:2] == (12, 2)
