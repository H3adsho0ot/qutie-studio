"""Module matrices for QR codes and 1-D barcodes, and integer-dot layout helpers."""
import barcode
import qrcode
from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q

SYMBOLOGIES = {"code128": "Code 128", "code39": "Code 39", "ean13": "EAN-13"}
QUIET_MODULES_QR = 2
QUIET_MODULES_BARCODE = 10
_ECC = {"L": ERROR_CORRECT_L, "M": ERROR_CORRECT_M, "Q": ERROR_CORRECT_Q, "H": ERROR_CORRECT_H}


def qr_matrix(data: str, ecc: str = "M") -> list[list[bool]]:
    """Square matrix of QR modules (True = dark), without quiet zone."""
    if not data:
        raise ValueError("QR code needs some text")
    qr = qrcode.QRCode(error_correction=_ECC.get(ecc, ERROR_CORRECT_M), border=0)
    qr.add_data(data)
    try:
        qr.make(fit=True)
    except Exception as exc:                       # data too long for the largest version
        raise ValueError(f"cannot encode QR data: {exc}") from exc
    return [list(row) for row in qr.get_matrix()]


def barcode_modules(symbology: str, data: str) -> tuple[list[bool], str]:
    """Return (dark/light module sequence, human-readable text) for a 1-D barcode."""
    if symbology not in SYMBOLOGIES:
        raise ValueError(f"unknown barcode type {symbology!r}")
    if not data:
        raise ValueError("barcode needs some data")
    try:
        code = barcode.get(symbology, data)
        pattern = code.build()[0]
        text = code.get_fullcode()
    except Exception as exc:
        raise ValueError(f"cannot encode {SYMBOLOGIES[symbology]}: {exc}") from exc
    return [c == "1" for c in pattern], text


def fit_scale(modules: int, quiet: int, width_dots: int, height_dots: int | None = None) -> int:
    """Largest integer dots-per-module so `modules` plus quiet zones fit; 0 if even 1 dot does not fit."""
    limit = width_dots if height_dots is None else min(width_dots, height_dots)
    return limit // (modules + 2 * quiet)
