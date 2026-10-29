import pytest
from PIL import Image

from qutie.designer import model


def sample_label():
    label = model.Label(length_mm=55.5, density=90, copies=3, feed_mm=6.0, rotation=90)
    picture = model.Picture(x=1, y=1, w=8, h=8)
    picture.set_image(Image.new("L", (4, 4), 0))
    label.elements = [
        model.Text(text="Hello\nworld", bold=True, size_pt=14, align="center", inverse=True),
        model.Shape(shape="ellipse", stroke_mm=0.8, fill=True),
        picture,
        model.QRCode(data="abc", ecc="H"),
        model.Barcode(data="4006381333931", symbology="ean13", show_text=False),
    ]
    return label


def test_json_roundtrip_keeps_everything():
    label = sample_label()
    loaded = model.Label.from_json(label.to_json())
    assert loaded.to_json() == label.to_json()
    assert [type(e) for e in loaded.elements] == [type(e) for e in label.elements]
    assert (loaded.length_mm, loaded.density, loaded.copies, loaded.feed_mm, loaded.rotation) == (55.5, 90, 3, 6, 90)
    assert loaded.elements[2].pil().size == (4, 4)


def test_size_in_dots():
    assert model.Label(length_mm=40).size_dots == (320, 96)


def test_defaults_for_missing_label_fields_and_clamped_length():
    loaded = model.Label.from_json('{"version": 1, "label": {"length_mm": 5000}, "elements": []}')
    assert loaded.length_mm == model.MAX_LENGTH_MM and loaded.rotation == 270 and loaded.feed_mm == 14.0


def test_unknown_fields_are_ignored_and_unknown_kinds_rejected():
    text = model.element_from_dict({"kind": "text", "text": "x", "future_option": 1})
    assert text.text == "x"
    with pytest.raises(ValueError):
        model.element_from_dict({"kind": "hologram"})


def test_newer_file_version_is_refused():
    with pytest.raises(ValueError):
        model.Label.from_json('{"version": 99, "elements": []}')


def test_copy_gets_new_id_and_same_content():
    original = model.Text(text="x", size_pt=20)
    clone = original.copy()
    assert clone.id != original.id and clone.text == "x" and clone.size_pt == 20


def test_find():
    label = sample_label()
    assert label.find(label.elements[1].id) is label.elements[1]
    assert label.find("nope") is None
