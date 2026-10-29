"""The print sequence shared by the CLI and the designer: image -> command stream -> printer."""
import time

from PIL import Image

from . import protocol, raster

_ROTATIONS = {
    0: None,
    90: Image.Transpose.ROTATE_90,     # counter-clockwise
    180: Image.Transpose.ROTATE_180,
    270: Image.Transpose.ROTATE_270,   # clockwise
}


def rotate(image: Image.Image, degrees: int) -> Image.Image:
    if degrees not in _ROTATIONS:
        raise ValueError("rotation must be 0, 90, 180 or 270")
    if image.mode in ("RGBA", "LA", "P"):        # flatten first so transparency prints as white
        image = image.convert("RGBA")
        canvas = Image.new("RGBA", image.size, "white")
        canvas.alpha_composite(image)
        image = canvas
    op = _ROTATIONS[degrees]
    return image if op is None else image.transpose(op)


def feed_command(rows: int, label_mm: float | None = None, feed_mm: float = 14.0) -> bytes:
    if label_mm:
        return protocol.cmd_feed_to_label(round(label_mm * protocol.DPMM))
    return protocol.cmd_feed(round(feed_mm * protocol.DPMM))


def build_job(image: Image.Image, density: int = 75, label_mm: float | None = None,
              feed_mm: float = 14.0, rotation: int = 0, width: int = protocol.HEAD_DOTS) -> list[bytes]:
    """Return the plain command chunks for one copy: density, raster blocks, feed."""
    width_bytes, rows, data = raster.to_raster(rotate(image, rotation), width)
    return ([protocol.cmd_density(density)] + raster.raster_blocks(width_bytes, data)
            + [feed_command(rows, label_mm, feed_mm)])


def send_image(session, image: Image.Image, copies: int = 1, progress=None, **options) -> int:
    """Print `copies` of `image` on an open Session; returns the number of raster rows per copy."""
    chunks = build_job(image, **options)
    for copy in range(copies):
        for chunk in chunks:
            session.send(chunk)
        if progress:
            progress(copy + 1, copies)
        time.sleep(0.1)
    session.flush()
    return raster.to_raster(rotate(image, options.get("rotation", 0)), options.get("width", protocol.HEAD_DOTS))[1]
