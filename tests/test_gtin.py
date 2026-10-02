"""GTIN-12 normalization for the spellings GS1 Data Hub and scanners produce."""

from greenlight.gtin import looks_like_gtin12, normalize_gtin12

UPC = "810238922216"  # real Sundial UPC from a Data Hub export


def test_forms_normalize_to_upc_a():
    assert normalize_gtin12(UPC) == UPC
    assert normalize_gtin12("00" + UPC) == UPC   # Data Hub GTIN-14 field
    assert normalize_gtin12("0" + UPC) == UPC    # EAN-13 scanner
    assert normalize_gtin12(UPC[:11]) == UPC     # spreadsheet dropped check digit
    assert normalize_gtin12("0081-0238-922216") == UPC


def test_bad_values_rejected():
    assert normalize_gtin12(UPC[:-1] + "7") is None        # wrong check digit
    assert normalize_gtin12("01" + UPC) is None            # real GTIN-14, not a UPC-A
    assert normalize_gtin12("00" + UPC[:-1] + "7") is None


def test_scan_guard_recognizes_every_form():
    for raw in (UPC, "0" + UPC, "00" + UPC):
        assert looks_like_gtin12(raw), raw
    assert not looks_like_gtin12("000123")
