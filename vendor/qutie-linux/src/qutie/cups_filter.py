"""CUPS filter: CUPS raster -> plain Qutie command stream (the backend adds the XOR)."""
import shlex
import sys

from PIL import Image

from . import cupsraster, protocol, raster

DEFAULT_DENSITY = 75
DEFAULT_FEED_MM = 14.0


def parse_options(text: str) -> dict[str, str]:
    options = {}
    for token in shlex.split(text or ""):
        name, _, value = token.partition("=")
        options[name] = value
    return options


def page_to_image(h: cupsraster.PageHeader, data: bytes) -> Image.Image:
    """Convert a raster page to an 8-bit grayscale image (255 = white)."""
    cs = h.color_space
    if h.bits_per_pixel == 1 and cs in (cupsraster.CSPACE_W, cupsraster.CSPACE_SW, cupsraster.CSPACE_K):
        img = Image.frombytes("1", (h.width, h.height), data, "raw", "1", h.bytes_per_line)
        img = img.convert("L")
        return Image.eval(img, lambda v: 255 - v) if cs == cupsraster.CSPACE_K else img
    if h.bits_per_color == 8 and h.bits_per_pixel == 8 and cs in (
            cupsraster.CSPACE_W, cupsraster.CSPACE_SW, cupsraster.CSPACE_K):
        img = Image.frombytes("L", (h.width, h.height), data, "raw", "L", h.bytes_per_line)
        return Image.eval(img, lambda v: 255 - v) if cs == cupsraster.CSPACE_K else img
    if h.bits_per_color == 8 and h.bits_per_pixel == 24 and cs in (cupsraster.CSPACE_RGB, cupsraster.CSPACE_SRGB):
        return Image.frombytes("RGB", (h.width, h.height), data, "raw", "RGB", h.bytes_per_line).convert("L")
    raise ValueError(f"unsupported raster format: {h.bits_per_color} bits/color, "
                     f"{h.bits_per_pixel} bits/pixel, colorspace {cs}")


def page_commands(h: cupsraster.PageHeader, data: bytes, options: dict[str, str], log=None) -> bytes:
    log = log or sys.stderr
    if h.width > protocol.HEAD_DOTS + 2:
        print(f"WARNING: page is {h.width} dots wide, the print head is {protocol.HEAD_DOTS}; scaling to fit", file=log)
    density = int(options.get("QutieDensity", DEFAULT_DENSITY))
    width_bytes, rows, packed = raster.to_raster(page_to_image(h, data))
    if options.get("QutieMedia", "Continuous") == "Gap":
        feed = protocol.cmd_feed_to_label(rows)
    else:
        feed = protocol.cmd_feed(round(float(options.get("QutieFeed", DEFAULT_FEED_MM)) * protocol.DPMM))
    return protocol.cmd_density(density) + b"".join(raster.raster_blocks(width_bytes, packed)) + feed


def run(stream_in, stream_out, options: dict[str, str], log=None) -> int:
    log = log or sys.stderr
    pages = 0
    for header, data in cupsraster.read_pages(stream_in):
        pages += 1
        stream_out.write(page_commands(header, data, options, log))
        stream_out.flush()
        print(f"PAGE: {pages} 1", file=log)
    return pages


def main(argv, stdin=None, stdout=None) -> int:
    # CUPS: filter job-id user title copies options [file]
    if len(argv) not in (6, 7):
        print(f"Usage: {argv[0]} job-id user title copies options [file]", file=sys.stderr)
        return 1
    options = parse_options(argv[5])
    try:
        source = open(argv[6], "rb") if len(argv) == 7 else (stdin or sys.stdin.buffer)
        run(source, stdout or sys.stdout.buffer, options)
    except (ValueError, EOFError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0
