import pytest
from PIL import Image

from qutie import job, protocol, raster


class FakeSession:
    def __init__(self):
        self.sent = []
        self.flushed = False

    def send(self, data):
        self.sent.append(data)

    def flush(self):
        self.flushed = True


def black_corner_image(size=(200, 96)):
    img = Image.new("L", size, 255)
    img.putpixel((0, 0), 0)    # top-left pixel
    return img


def test_rotation_directions():
    # PIL ROTATE_90 is counter-clockwise: top-left -> bottom-left; ROTATE_270 clockwise: top-left -> top-right
    ccw = job.rotate(black_corner_image(), 90)
    assert ccw.size == (96, 200) and ccw.getpixel((0, 199)) == 0
    cw = job.rotate(black_corner_image(), 270)
    assert cw.size == (96, 200) and cw.getpixel((95, 0)) == 0
    assert job.rotate(black_corner_image(), 0).getpixel((0, 0)) == 0
    assert job.rotate(black_corner_image(), 180).getpixel((199, 95)) == 0


def test_bad_rotation_rejected():
    with pytest.raises(ValueError):
        job.rotate(black_corner_image(), 45)


def test_transparency_is_flattened_to_white_before_rotating():
    img = Image.new("RGBA", (200, 96), (0, 0, 0, 0))
    assert job.rotate(img, 90).convert("L").getextrema() == (255, 255)


def test_build_job_layout():
    chunks = job.build_job(Image.new("L", (96, 130), 0), density=90, feed_mm=2)
    assert chunks[0] == protocol.cmd_density(90)
    assert chunks[-1] == protocol.cmd_feed(16)
    assert len(chunks) == 2 + 3                      # 130 rows -> 3 raster blocks of <= 60 rows


def test_build_job_rotates_before_rasterising():
    chunks = job.build_job(black_corner_image(), rotation=270)
    width_bytes, rows, data = raster.to_raster(job.rotate(black_corner_image(), 270))
    assert (width_bytes, rows) == (12, 200)
    assert data[11] == 0x01                          # top-right dot is the very first row's last bit
    assert len(chunks) == 2 + 4                      # 200 rows -> 60+60+60+20


def test_label_mm_uses_feed_to_label():
    chunks = job.build_job(Image.new("L", (96, 8), 0), label_mm=30)
    assert chunks[-1] == protocol.cmd_feed_to_label(240)


def test_send_image_sends_every_copy_then_flushes():
    s = FakeSession()
    seen = []
    rows = job.send_image(s, Image.new("L", (96, 20), 0), copies=3, progress=lambda i, n: seen.append((i, n)))
    assert rows == 20 and s.flushed and seen == [(1, 3), (2, 3), (3, 3)]
    assert s.sent.count(protocol.cmd_density(75)) == 3
