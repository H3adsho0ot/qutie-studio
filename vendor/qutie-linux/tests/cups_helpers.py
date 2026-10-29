"""Build CUPS raster streams for tests."""
import struct


def header(width, height, bits_per_color, bits_per_pixel, bytes_per_line, color_space, order="<", size=1796):
    raw = bytearray(size)
    for off, val in ((340, 1), (352, 34), (356, 85), (372, width), (376, height), (384, bits_per_color),
                     (388, bits_per_pixel), (392, bytes_per_line), (400, color_space)):
        struct.pack_into(order + "I", raw, off, val)
    raw[128:128 + 5] = b"label"
    return bytes(raw)


def rle_encode(rows, bpp):
    """Encode rows (bytes) CUPS-style; identical consecutive rows are folded into a repeat count."""
    out = bytearray()
    i = 0
    while i < len(rows):
        repeat = 1
        while i + repeat < len(rows) and rows[i + repeat] == rows[i] and repeat < 256:
            repeat += 1
        out.append(repeat - 1)
        line = rows[i]
        pixels = [line[p:p + bpp] for p in range(0, len(line), bpp)]
        j = 0
        while j < len(pixels):
            run = 1
            while j + run < len(pixels) and pixels[j + run] == pixels[j] and run < 128:
                run += 1
            if run > 1:
                out.append(run - 1)
                out += pixels[j]
                j += run
            else:
                lit = 1
                while j + lit < len(pixels) and lit < 127 and not (
                        j + lit + 1 < len(pixels) and pixels[j + lit] == pixels[j + lit + 1]):
                    lit += 1
                if lit == 1:
                    out.append(0)
                else:
                    out.append(257 - lit)
                out += b"".join(pixels[j:j + lit])
                j += lit
        i += repeat
    return bytes(out)


def stream(pages, version="RaS2", little=True):
    """pages: list of (width, height, bits_per_color, bits_per_pixel, color_space, rows list)."""
    order = "<" if little else ">"
    sync = {"RaSt": b"RaSt", "RaS2": b"RaS2", "RaS3": b"RaS3"}[version]
    out = bytearray(sync[::-1] if little else sync)
    for width, height, bpc, bpp, cs, rows in pages:
        bytes_per_line = len(rows[0])
        out += header(width, height, bpc, bpp, bytes_per_line, cs, order, 420 if version == "RaSt" else 1796)
        out += rle_encode(rows, max(1, (bpp + 7) // 8)) if version == "RaS2" else b"".join(rows)
    return bytes(out)
