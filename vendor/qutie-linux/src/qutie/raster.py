"""Image to printer raster conversion."""
from PIL import Image

from . import lzo, protocol


def to_raster(image: Image.Image, width: int = protocol.HEAD_DOTS) -> tuple[int, int, bytes]:
    """Return (width_bytes, rows, packed 1 bpp data), MSB first, 1 = black.

    Images wider than `width` are scaled down, narrower ones centred on white.
    """
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        canvas = Image.new("RGBA", image.size, "white")
        canvas.alpha_composite(image)
        image = canvas
    gray = image.convert("L")
    if gray.width > width:
        gray = gray.resize((width, max(1, round(gray.height * width / gray.width))), Image.LANCZOS)
    if gray.width < width:
        canvas = Image.new("L", (width, gray.height), 255)
        canvas.paste(gray, ((width - gray.width) // 2, 0))
        gray = canvas
    bw = gray.point(lambda v: 255 if v >= 128 else 0).convert("1")
    # PIL mode "1" packs MSB first with 1 = white; the printer wants 1 = black.
    packed = bytes(b ^ 0xFF for b in bw.tobytes())
    return (width + 7) // 8, gray.height, packed


def raster_blocks(width_bytes: int, data: bytes) -> list[bytes]:
    blocks = []
    for chunk in protocol.split_rows(data, width_bytes):
        blocks.append(protocol.raster_block(lzo.compress(chunk), width_bytes, len(chunk) // width_bytes))
    return blocks
