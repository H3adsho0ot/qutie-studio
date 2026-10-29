"""Render a label document to the image that gets printed (and shown in the "as printed" preview)."""
import os

import math

from PIL import Image, ImageChops
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from .canvas import LabelScene
from .model import Label

_app = None


def ensure_app() -> QApplication:
    """A QApplication is needed for fonts and graphics items, even without a window."""
    global _app
    app = QApplication.instance()
    if app is None:
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _app = app = QApplication([])
    return app


def render_scene(scene: LabelScene, source: QRectF | None = None) -> Image.Image:
    """Landscape grayscale image, one pixel per printer dot, anti-aliased text, not yet thresholded.

    `source` (scene coordinates, default the whole label) selects another region, e.g. to see content that
    sticks out of the label."""
    width, height = scene.doc.size_dots
    source = source or QRectF(0, 0, width, height)
    out_w, out_h = max(1, round(source.width())), max(1, round(source.height()))
    image = QImage(out_w, out_h, QImage.Format_Grayscale8)
    image.fill(QColor(255, 255, 255))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    selected = scene.selectedItems()
    scene.clearSelection()
    scene.printing = True
    try:
        scene.render(painter, QRectF(0, 0, out_w, out_h), source)
    finally:
        scene.printing = False
        for item in selected:
            item.setSelected(True)
        painter.end()
    return Image.frombytes("L", (out_w, out_h), bytes(image.constBits()), "raw", "L", image.bytesPerLine())


def render_label(doc: Label) -> Image.Image:
    ensure_app()
    return render_scene(LabelScene(doc))


def threshold(image: Image.Image, level: int = 128) -> Image.Image:
    """The exact black/white decision the printer path makes (see qutie.raster.to_raster)."""
    return image.point(lambda v: 255 if v >= level else 0)


def ink_extent(image: Image.Image, level: int = 128) -> tuple[int, int] | None:
    """Columns [left, right) that contain black dots after thresholding, or None for a blank image."""
    bbox = ImageChops.invert(threshold(image, level)).getbbox()
    return None if bbox is None else (bbox[0], bbox[2])


def trim_to_content(image: Image.Image, margin_dots: int) -> Image.Image:
    """Crop away blank columns before and after the ink, keeping `margin_dots` of white on each side."""
    extent = ink_extent(image)
    if extent is None:
        return image
    left, right = extent
    out = Image.new("L", (right - left + 2 * margin_dots, image.height), 255)
    out.paste(image.crop((left, 0, right, image.height)), (margin_dots, 0))
    return out


def content_extent(scene: LabelScene) -> tuple[int, int] | None:
    """Ink extent in label dot coordinates, including parts of elements that stick out of the label."""
    items = [scene.item_for(e.id) for e in scene.doc.elements]
    boxes = [i.mapRectToScene(0, 0, i.width, i.height) for i in items if i is not None]
    if not boxes:
        return None
    union = boxes[0]
    for box in boxes[1:]:
        union = union.united(box)
    left = math.floor(union.left()) - 4
    region = QRectF(left, 0, math.ceil(union.width()) + 8, scene.doc.size_dots[1])
    extent = ink_extent(render_scene(scene, region))
    return None if extent is None else (left + extent[0], left + extent[1])
