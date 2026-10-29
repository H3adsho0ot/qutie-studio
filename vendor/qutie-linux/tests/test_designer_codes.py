import pytest

from qutie.designer import codes


def test_qr_matrix_is_square_and_has_finder_pattern():
    m = codes.qr_matrix("https://example.org")
    assert len(m) == len(m[0]) == 25
    assert all(m[0][:7]) and all(m[6][:7]) and not m[1][1] and m[2][2]    # top-left finder pattern


def test_qr_error_correction_changes_size():
    data = "x" * 40
    assert len(codes.qr_matrix(data, "L")) < len(codes.qr_matrix(data, "H"))


@pytest.mark.parametrize("data", ["", "x" * 10000])
def test_qr_rejects_empty_and_oversized(data):
    with pytest.raises(ValueError):
        codes.qr_matrix(data)


def test_code128_structure():
    modules, text = codes.barcode_modules("code128", "HELLO-123")
    assert text == "HELLO-123"
    assert len(modules) == 11 * (1 + 9 + 1) + 13           # start, data, checksum, stop
    assert "".join("1" if m else "0" for m in modules[:11]) == "11010010000"   # start code B


def test_ean13_checksum_is_added():
    modules, text = codes.barcode_modules("ean13", "590123412345")
    assert text == "5901234123457" and len(modules) == 95


@pytest.mark.parametrize("symbology,data", [("ean13", "abc"), ("ean13", "123"), ("code39", "a!b"), ("code128", ""),
                                            ("pdf417", "x")])
def test_barcode_errors_are_value_errors(symbology, data):
    with pytest.raises(ValueError):
        codes.barcode_modules(symbology, data)


def test_fit_scale():
    assert codes.fit_scale(25, 2, 80, 80) == 2          # 29 modules in 80 dots
    assert codes.fit_scale(25, 2, 80, 40) == 1          # height limits it
    assert codes.fit_scale(134, 0, 100) == 0            # does not fit at all
