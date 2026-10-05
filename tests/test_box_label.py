#!/usr/bin/env python3
"""Geometry tests for the retail box label (2" x 3", UPC-A).

`box_label` predates these tests and had never been printed, which let three
horizontal defects sit in it undetected: the brand text ran 6 dots into the
logo bitmap, a long LTD SKU ran 18 dots off the right edge, and the subtitle
was sent unclipped at any length. All three came from laying text out with the
font cell widths in the TSPL manual instead of the printer's actual advance
(~2 dots more per character), and all three were invisible to the script's
`--preview`, which only checked the barcode band.

So: measure every element with TSCLabelPrinter.FONT_ADVANCE and assert nothing
leaves the label or lands on anything else.

Run: pytest tests/test_box_label.py  (no DB, no Shopify, no printer)
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenlight.hardware.tsc_label_printer import TSCLabelPrinter

# Cell heights in dots; widths come from the printer's own advance table so
# the two can't drift apart.
_FONT_H = {"1": 12, "2": 20, "3": 24, "4": 32, "5": 48}

_TEXT_RE = re.compile(r'TEXT (\d+),(\d+),"(\d)",0,(\d+),(\d+),"([^"]*)"')
_BITMAP_RE = re.compile(r"BITMAP (\d+),(\d+),(\d+),(\d+),")
_BAR_RE = re.compile(r"BAR (\d+),(\d+),(\d+),(\d+)")

# A valid GTIN-12 (check digit 2), so the template renders rather than raising.
UPC = "036000291452"


@pytest.fixture(scope="module")
def printer():
    """A generator-only printer. 'preview' is never resolved — nothing dials."""
    return TSCLabelPrinter(ip_address="preview")


def elements(printer, data):
    """Element boxes from a rendered box label: (label, x, y, w, h).

    The BITMAP command carries raw binary pixel data, so the TSPL is decoded
    as latin-1 and the bitmap is measured from its header rather than parsed
    as text.
    """
    txt = printer._generate_box_label_tspl(data).decode("latin-1")
    out = []
    for m in _TEXT_RE.finditer(txt):
        font, text = m.group(3), m.group(6)
        xm, ym = int(m.group(4)), int(m.group(5))
        out.append((repr(text), int(m.group(1)), int(m.group(2)),
                    len(text) * printer.FONT_ADVANCE[font] * xm,
                    _FONT_H[font] * ym))
    for m in _BITMAP_RE.finditer(txt):
        x, y, width_bytes, h = (int(g) for g in m.groups())
        out.append(("wire logo", x, y, width_bytes * 8, h))
    for m in _BAR_RE.finditer(txt):
        x, y, w, h = (int(g) for g in m.groups())
        out.append(("rule", x, y, w, h))
    return out


def text_values(printer, data):
    txt = printer._generate_box_label_tspl(data).decode("latin-1")
    return [m.group(6) for m in _TEXT_RE.finditer(txt)]


def assert_fits(printer, data, label=""):
    """No element may leave the label or overlap another."""
    boxes = elements(printer, data)
    w = int(float(data.get("label_width_mm", printer.BOX_LABEL_WIDTH_MM))
            * printer.dpi / 25.4)
    h = int(float(data.get("label_height_mm", printer.BOX_LABEL_HEIGHT_MM))
            * printer.dpi / 25.4)
    for name, x, y, bw, bh in boxes:
        assert x >= 2 and y >= 2, f"{label}: {name} starts off-label ({x},{y})"
        assert x + bw <= w, f"{label}: {name} runs {x + bw - w} dots past the right edge"
        assert y + bh <= h, f"{label}: {name} runs {y + bh - h} dots past the bottom"
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if (a[1] < b[1] + b[3] and b[1] < a[1] + a[3]
                    and a[2] < b[2] + b[4] and b[2] < a[2] + a[4]):
                pytest.fail(f"{label}: {a[0]} overlaps {b[0]}")
    return boxes


# --------------------------------------------------------------------------
# The three defects this file exists for
# --------------------------------------------------------------------------

def test_brand_text_does_not_run_into_the_logo(printer):
    """The logo used to be pinned at a hardcoded x=140, close enough to the
    end of "SUNDIAL" that any error in the font width collided with it."""
    boxes = assert_fits(printer, {"upc": UPC}, "brand")
    sundial = next(b for b in boxes if "SUNDIAL" in b[0])
    logo = next(b for b in boxes if b[0] == "wire logo")
    audio = next(b for b in boxes if "AUDIO" in b[0])
    assert sundial[1] + sundial[3] <= logo[1]
    assert logo[1] + logo[3] <= audio[1]


@pytest.mark.parametrize("sku", [
    "SC-20GL", "TC-15HP-R", "SV-25MB", "SC-12-LTD-PHISH26-R", "SC-MISC-142",
])
def test_sku_stays_on_the_label(printer, sku):
    """A 19-character LTD SKU ran 18 dots off the edge at font "2"; it should
    drop to font "1" rather than overflow."""
    assert_fits(printer, {"upc": UPC, "sku": sku,
                          "product_title": "Studio Classic",
                          "subtitle": "20 ft"}, sku)


def test_the_longest_real_sku_still_fits_at_font_2(printer):
    """19 characters at font "2" is 266 dots on the measured advance of 14,
    against 228 on the manual's 12 -- which is why it was overflowing."""
    txt = printer._generate_box_label_tspl(
        {"upc": UPC, "sku": "SC-12-LTD-PHISH26-R"}).decode("latin-1")
    m = next(m for m in _TEXT_RE.finditer(txt)
             if m.group(6) == "SC-12-LTD-PHISH26-R")
    assert m.group(3) == "2"
    end = int(m.group(1)) + 19 * printer.FONT_ADVANCE["2"]
    assert end <= printer.label_width_dots


def test_an_implausibly_long_sku_drops_to_the_smaller_font(printer):
    """Past what font "2" can fit beside the brand block it steps down rather
    than overflowing, and clips rather than running over "AUDIO"."""
    sku = "SC-12-LTD-SOMETHING-RIDICULOUS-R"
    boxes = assert_fits(printer, {"upc": UPC, "sku": sku}, sku)
    txt = printer._generate_box_label_tspl(
        {"upc": UPC, "sku": sku}).decode("latin-1")
    rendered = next(m for m in _TEXT_RE.finditer(txt)
                    if sku.startswith(m.group(6)))
    assert rendered.group(3) == "1"
    audio = next(b for b in boxes if "AUDIO" in b[0])
    assert int(rendered.group(1)) >= audio[1] + audio[3]


def test_subtitle_is_clipped_to_the_row(printer):
    """It comes from Shopify's variant title, so it can be any length. It was
    sent as-is, with no clip at all."""
    boxes = assert_fits(printer, {"upc": UPC, "sku": "SC-20GL",
                                  "product_title": "Studio Classic",
                                  "subtitle": "x" * 200}, "long subtitle")
    row = next(b for b in boxes if "xxx" in b[0])
    usable = printer.label_width_dots - 2 * 20
    assert row[3] <= usable


def test_title_wraps_and_clips(printer):
    values = text_values(printer, {
        "upc": UPC,
        "product_title": "Sundial Studio Classic Goldline Instrument Cable "
                         "Twenty Foot Straight",
    })
    usable = printer.label_width_dots - 2 * 20
    for v in values:
        assert len(v) * printer.FONT_ADVANCE["3"] <= usable


# --------------------------------------------------------------------------
# Text safety — these strings come from Shopify
# --------------------------------------------------------------------------

def test_shopify_punctuation_is_folded_to_ascii(printer):
    """The TE210's bitmap fonts render a single-byte codepage, so an en-dash
    or a smart quote out of a Shopify title would print as garbage."""
    values = text_values(printer, {
        "upc": UPC,
        "product_title": "Sundial – Studio “Classic”",
        "subtitle": "20′ – TS–TS",
    })
    joined = " ".join(values)
    assert all(32 <= ord(c) < 127 for c in joined), joined
    assert "Sundial - Studio 'Classic'" in values
    # The prime folds to an apostrophe rather than being dropped.
    assert "20' - TS-TS" in values


def test_a_quote_in_a_title_cannot_break_the_tspl(printer):
    """TSPL delimits TEXT content with `"` and cannot escape one, so an
    unescaped quote would truncate the command and leave the rest to be read
    as TSPL."""
    txt = printer._generate_box_label_tspl({
        "upc": UPC, "product_title": 'The "Best" Cable', "subtitle": 'PRINT 9"',
    }).decode("latin-1")
    for line in txt.split("\r\n"):
        if line.startswith("TEXT"):
            assert _TEXT_RE.fullmatch(line), f"malformed TEXT: {line}"


# --------------------------------------------------------------------------
# Barcode geometry (the part that was already right — keep it that way)
# --------------------------------------------------------------------------

def test_two_inch_stock_uses_the_in_spec_module_width(printer):
    txt = printer._generate_box_label_tspl({"upc": UPC}).decode("latin-1")
    m = re.search(r'BARCODE (\d+),(\d+),"UPCA",(\d+),1,0,(\d+),', txt)
    assert int(m.group(4)) == 3, "2in stock should give narrow=3 (113.7%)"


def test_one_inch_stock_falls_back_and_drops_the_branding(printer):
    """Short stock degrades to a barcode-only sticker rather than printing
    text over the bars."""
    txt = printer._generate_box_label_tspl(
        {"upc": UPC, "product_title": "Studio Classic",
         "label_height_mm": 25.4}).decode("latin-1")
    m = re.search(r'BARCODE (\d+),(\d+),"UPCA",(\d+),1,0,(\d+),', txt)
    assert int(m.group(4)) == 2
    assert "TEXT" not in txt


def test_the_printer_gets_eleven_digits_not_twelve(printer):
    """TSPL's UPCA type computes the check digit itself, which makes the
    printer an independent check on gtin.check_digit()."""
    txt = printer._generate_box_label_tspl({"upc": UPC}).decode("latin-1")
    m = re.search(r'"UPCA",\d+,1,0,\d+,\d+,"(\d+)"', txt)
    assert m.group(1) == UPC[:11]


@pytest.mark.parametrize("bad", ["", None, "036000291453", "abc", "12345"])
def test_an_invalid_gtin_is_refused(printer, bad):
    """A box label with a wrong barcode is worse than no box label."""
    with pytest.raises(ValueError):
        printer._generate_box_label_tspl({"upc": bad})


def test_font_advance_table_matches_the_printers(printer):
    """These tests only mean something if they measure with the same advance
    the template lays out with."""
    assert printer.FONT_ADVANCE == {"1": 10, "2": 14, "3": 16, "4": 24, "5": 32}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
