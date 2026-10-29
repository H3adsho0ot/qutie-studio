import pytest
from PIL import Image

from qutie import lzo, protocol, raster


def test_bit_order_msb_first_black_is_one():
    img = Image.new("L", (96, 2), 255)
    img.putpixel((0, 0), 0)    # first pixel of row 0 -> 0x80
    img.putpixel((95, 1), 0)   # last pixel of row 1 -> 0x01
    width_bytes, rows, data = raster.to_raster(img)
    assert (width_bytes, rows) == (12, 2)
    assert data[0] == 0x80 and data[12 + 11] == 0x01
    assert data[1:12] == bytes(11)


def test_narrow_image_is_centred_on_white():
    img = Image.new("L", (16, 1), 0)
    _, _, data = raster.to_raster(img, width=96)
    assert data == bytes(5) + b"\xff\xff" + bytes(5)


def test_wide_image_is_scaled_to_width():
    _, rows, _ = raster.to_raster(Image.new("L", (192, 40), 0))
    assert rows == 20


def test_transparent_pixels_print_as_white():
    img = Image.new("RGBA", (96, 1), (0, 0, 0, 0))
    _, _, data = raster.to_raster(img)
    assert data == bytes(12)


def test_literal_only_stream_shape():
    assert lzo.literal_only(b"abc") == bytes([20]) + b"abc" + b"\x11\x00\x00"


@pytest.mark.skipif(lzo._load() is None, reason="liblzo2 not installed")
@pytest.mark.parametrize("size", [1, 100, 238, 239, 700, 5000])
def test_lzo_roundtrip(size):
    data = bytes((i * 7) % 251 for i in range(size))
    assert lzo.decompress(lzo.compress(data), size + 16) == data
    assert lzo.decompress(lzo.literal_only(data), size + 16) == data


@pytest.mark.skipif(lzo._load() is None, reason="liblzo2 not installed")
def test_blocks_decode_back_to_image():
    img = Image.effect_noise((96, 130), 90).convert("L")
    width_bytes, rows, data = raster.to_raster(img)
    blocks = raster.raster_blocks(width_bytes, data)
    assert len(blocks) == 3
    rebuilt = b""
    for block in blocks:
        assert block[:4] == bytes.fromhex("1d763030")
        length = int.from_bytes(block[8:12], "little")
        rows_in_block = int.from_bytes(block[6:8], "little")
        rebuilt += lzo.decompress(block[12:12 + length], rows_in_block * width_bytes)
    assert rebuilt == data
