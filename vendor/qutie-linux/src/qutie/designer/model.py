"""Label document model: plain data, no Qt. All geometry is in millimetres."""
import base64
import io
import json
import uuid
from dataclasses import dataclass, field, fields

from PIL import Image

FORMAT_VERSION = 1
HEIGHT_MM = 12.0          # fixed by the print head (96 dots at 8 dots/mm)
MIN_LENGTH_MM, MAX_LENGTH_MM = 4.0, 300.0
DOTS_PER_MM = 8


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Element:
    kind = ""
    id: str = field(default_factory=new_id)
    x: float = 0.0
    y: float = 0.0
    w: float = 10.0
    h: float = 5.0
    rotation: float = 0.0     # degrees, clockwise, around the centre

    def to_dict(self) -> dict:
        data = {f.name: getattr(self, f.name) for f in fields(self)}
        data["kind"] = self.kind
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Element":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def copy(self) -> "Element":
        clone = type(self).from_dict(self.to_dict())
        clone.id = new_id()
        return clone


@dataclass
class Text(Element):
    kind = "text"
    w: float = 30.0
    h: float = 8.0
    text: str = "Text"
    font: str = "DejaVu Sans"
    size_pt: float = 12.0
    bold: bool = False
    italic: bool = False
    underline: bool = False
    align: str = "left"        # left | center | right
    line_spacing: float = 1.0
    inverse: bool = False      # white text on a black box


@dataclass
class Shape(Element):
    kind = "shape"
    shape: str = "rect"        # rect | ellipse | line
    stroke_mm: float = 0.5
    fill: bool = False


@dataclass
class Picture(Element):
    kind = "image"
    w: float = 10.0
    h: float = 10.0
    png_b64: str = ""
    threshold: int = 128
    dither: bool = False
    keep_aspect: bool = True

    def pil(self) -> Image.Image | None:
        if not self.png_b64:
            return None
        return Image.open(io.BytesIO(base64.b64decode(self.png_b64)))

    def set_image(self, image: Image.Image) -> None:
        buf = io.BytesIO()
        image.save(buf, "PNG")
        self.png_b64 = base64.b64encode(buf.getvalue()).decode("ascii")


@dataclass
class QRCode(Element):
    kind = "qr"
    w: float = 10.0
    h: float = 10.0
    data: str = "https://example.org"
    ecc: str = "M"             # L | M | Q | H


@dataclass
class Barcode(Element):
    kind = "barcode"
    w: float = 30.0
    h: float = 9.0
    data: str = "123456789"
    symbology: str = "code128"  # code128 | code39 | ean13
    show_text: bool = True


ELEMENT_TYPES = {cls.kind: cls for cls in (Text, Shape, Picture, QRCode, Barcode)}


def element_from_dict(data: dict) -> Element:
    try:
        return ELEMENT_TYPES[data["kind"]].from_dict(data)
    except KeyError as exc:
        raise ValueError(f"unknown element kind {data.get('kind')!r}") from exc


@dataclass
class Label:
    length_mm: float = 40.0
    density: int = 75
    copies: int = 1
    feed_mm: float = 14.0      # paper fed after each label so it can be torn off
    trim: bool = True          # print only the inked part (plus margin): no blank tape before or after
    trim_margin_mm: float = 1.0
    rotation: int = 270        # degrees applied when printing (landscape design -> head); see docs/designer.md
    elements: list[Element] = field(default_factory=list)

    @property
    def size_dots(self) -> tuple[int, int]:
        return round(self.length_mm * DOTS_PER_MM), round(HEIGHT_MM * DOTS_PER_MM)

    def find(self, element_id: str) -> Element | None:
        return next((e for e in self.elements if e.id == element_id), None)

    def to_json(self) -> str:
        return json.dumps({
            "version": FORMAT_VERSION,
            "label": {"length_mm": self.length_mm, "density": self.density, "copies": self.copies,
                      "feed_mm": self.feed_mm, "trim": self.trim, "trim_margin_mm": self.trim_margin_mm,
                      "rotation": self.rotation},
            "elements": [e.to_dict() for e in self.elements],
        }, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Label":
        data = json.loads(text)
        if data.get("version", 0) > FORMAT_VERSION:
            raise ValueError(f"label file version {data['version']} is newer than this program supports")
        meta = data.get("label", {})
        label = cls(
            length_mm=float(meta.get("length_mm", 40.0)),
            density=int(meta.get("density", 75)),
            copies=int(meta.get("copies", 1)),
            feed_mm=float(meta.get("feed_mm", 14.0)),
            trim=bool(meta.get("trim", False)),          # files from before this option keep printing as designed
            trim_margin_mm=min(10.0, max(0.0, float(meta.get("trim_margin_mm", 1.0)))),
            rotation=int(meta.get("rotation", 270)),
        )
        label.length_mm = min(MAX_LENGTH_MM, max(MIN_LENGTH_MM, label.length_mm))
        label.elements = [element_from_dict(e) for e in data.get("elements", [])]
        return label
