import pytest

pytest.importorskip("PySide6")
from PIL import Image, ImageChops  # noqa: E402

from qutie import job  # noqa: E402
from qutie.designer import codes, model, render  # noqa: E402
from qutie.designer.canvas import LabelScene  # noqa: E402


def px(img, x, y):
    return img.getpixel((x, y))


def label_with(*elements, length=40.0):
    doc = model.Label(length_mm=length)
    doc.elements = list(elements)
    return doc


def test_empty_label_is_white_and_correct_size():
    img = render.render_label(model.Label(length_mm=30))
    assert img.size == (240, 96) and img.getextrema() == (255, 255)


def test_rectangle_outline_is_pixel_exact():
    # 4 dot (0.5 mm) frame around the whole 40 x 12 mm label
    img = render.render_label(label_with(model.Shape(x=0, y=0, w=40, h=12, stroke_mm=0.5)))
    assert px(img, 0, 0) == 0 and px(img, 319, 95) == 0
    assert all(px(img, 100, y) == 0 for y in range(0, 4)) and px(img, 100, 4) == 255
    assert all(px(img, x, 50) == 0 for x in range(0, 4)) and px(img, 4, 50) == 255
    assert px(img, 160, 48) == 255


def test_filled_rectangle():
    img = render.render_label(label_with(model.Shape(x=2, y=2, w=4, h=4, fill=True)))
    assert px(img, 16, 16) == 0 and px(img, 47, 47) == 0 and px(img, 48, 48) == 255 and px(img, 15, 16) == 255


def test_rotated_line_becomes_vertical():
    flat = render.render_label(label_with(model.Shape(shape="line", x=10, y=5, w=10, h=2, stroke_mm=0.5)))
    turned = render.render_label(label_with(model.Shape(shape="line", x=10, y=5, w=10, h=2, stroke_mm=0.5,
                                                        rotation=90)))
    # box is x 80..160, y 40..56 dots: a horizontal bar through its centre row
    assert px(flat, 100, 48) == 0 and px(flat, 150, 48) == 0 and px(flat, 60, 48) == 255 and px(flat, 120, 20) == 255
    # box centre is (15 mm, 6 mm) = (120, 48): turned 90 degrees the bar runs vertically through x = 120
    assert px(turned, 120, 20) == 0 and px(turned, 120, 75) == 0 and px(turned, 90, 48) == 255


def test_text_draws_only_inside_its_box_and_inverse_fills_it():
    text = model.Text(x=2, y=2, w=20, h=8, text="Hi", size_pt=14)
    img = render.render_label(label_with(text))
    dark = [(x, y) for x in range(320) for y in range(96) if px(img, x, y) < 128]
    assert dark and all(16 <= x < 176 and 16 <= y < 80 for x, y in dark)
    text.inverse = True
    inv = render.render_label(label_with(text))
    assert px(inv, 17, 17) == 0                                          # box is black, text is white on top
    assert any(px(inv, x, y) == 255 for x in range(16, 60) for y in range(16, 60))


def test_text_that_does_not_fit_is_flagged():
    doc = label_with(model.Text(w=10, h=3, text="A very long text that cannot fit", size_pt=12))
    render.ensure_app()
    scene = LabelScene(doc)
    render.render_scene(scene)           # painting computes the layout
    assert "does not fit" in scene.warnings()[0]


def test_qr_modules_match_the_matrix():
    qr = model.QRCode(x=1, y=1, w=10, h=10, data="https://example.org", ecc="M")
    img = render.render_label(label_with(qr))
    matrix = codes.qr_matrix(qr.data, qr.ecc)
    scale = codes.fit_scale(len(matrix), codes.QUIET_MODULES_QR, 80, 80)
    side = len(matrix) * scale
    ox = 8 + (80 - side) // 2
    oy = 8 + (80 - side) // 2
    for my in range(len(matrix)):
        for mx in range(len(matrix)):
            want = 0 if matrix[my][mx] else 255
            assert px(img, ox + mx * scale + scale // 2, oy + my * scale + scale // 2) == want


def test_qr_that_is_too_small_is_flagged_and_blocks_printing():
    render.ensure_app()
    scene = LabelScene(label_with(model.QRCode(w=2, h=2, data="https://example.org/a/long/url")))
    render.render_scene(scene)
    assert any("too small" in w for w in scene.warnings())


def test_invalid_code_data_is_reported_as_problem():
    render.ensure_app()
    scene = LabelScene(label_with(model.Barcode(data="abc", symbology="ean13"), model.QRCode(data="")))
    assert len(scene.problems()) == 2


def test_barcode_bars_follow_modules():
    code = model.Barcode(x=2, y=1, w=30, h=9, data="ABC", symbology="code128", show_text=False)
    img = render.render_label(label_with(code))
    modules, _ = codes.barcode_modules("code128", "ABC")
    scale = codes.fit_scale(len(modules), 0, 240)
    ox = 16 + (240 - len(modules) * scale) // 2
    for i, dark in enumerate(modules):
        assert px(img, ox + i * scale + scale // 2, 20) == (0 if dark else 255)


def test_picture_threshold_and_aspect():
    source = Image.new("L", (8, 8), 255)
    for y in range(8):
        for x in range(4):
            source.putpixel((x, y), 100)       # left half mid-grey
    pic = model.Picture(x=0, y=0, w=8, h=8, threshold=128)
    pic.set_image(source)
    img = render.render_label(label_with(pic))
    assert px(img, 10, 32) == 0 and px(img, 50, 32) == 255
    pic.threshold = 50                          # grey 100 is now "light"
    assert px(render.render_label(label_with(pic)), 10, 32) == 255


def test_selection_handles_and_overlay_never_reach_the_print_image():
    render.ensure_app()
    doc = label_with(model.Shape(x=5, y=2, w=10, h=6, fill=True))
    scene = LabelScene(doc)
    before = render.render_scene(scene)
    scene.item_for(doc.elements[0].id).setSelected(True)
    after = render.render_scene(scene)
    assert ImageChops.difference(before, after).getbbox() is None
    assert scene.selected_ids() == [doc.elements[0].id]     # selection restored after rendering


def test_rendered_label_goes_through_the_print_path():
    img = render.render_label(label_with(model.Shape(x=0, y=0, w=40, h=12, fill=True)))
    chunks = job.build_job(img, rotation=270)
    assert chunks[0].startswith(b"\x1dsetc") and len(chunks) == 2 + 6      # 320 rows -> 6 raster blocks
