#!/usr/bin/env python3
"""Tests for the retail shelf label (box side) and its catalog description.

The point of the sweep tests: a shelf label's text is catalog data, and the
catalog grows. A new pattern with a long description, or a new series with a
long product line name, must not silently push text off the edge of the label
or print it on top of something else — the TE210 does both without complaint,
and you only find out after a roll of stock. So every catalog variant is
rendered and its element boxes are checked against the label bounds and each
other.

Run: pytest tests/test_shelf_label.py  (no DB, no Shopify, no printer)
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenlight.cable_config import (
    all_patterns, all_series, describe_variant, format_variant_sku,
    retail_cable_type, RETAIL_CABLE_TYPES,
)
from greenlight.hardware.tsc_label_printer import TSCLabelPrinter, _tspl_safe

# Row order, top to bottom, with the font each one prints in.
_ROWS = [("brand_line", "3", 16), ("pattern", "3", 16),
         ("spec_line", "4", 24), ("connector_line", "2", 14)]

# (horizontal advance, cell height) in dots at 203 DPI, mirroring
# TSCLabelPrinter.FONT_ADVANCE -- measured on the printer, not taken from the
# TSPL manual. Fonts "1" and "2" advance 2 dots more than it says; "3", "4"
# and "5" match. Using the manual's figures here made the bounds checks too
# generous, which is how an over-wide row reached real stock.
_FONT = {"1": (10, 12), "2": (14, 20), "3": (16, 24), "4": (24, 32),
         "5": (32, 48)}

_TEXT_RE = re.compile(r'TEXT (\d+),(\d+),"(\d)",0,(\d+),(\d+),"([^"]*)"')
_BAR_RE = re.compile(r"BAR (\d+),(\d+),(\d+),(\d+)")


@pytest.fixture(scope="module")
def printer():
    """A generator-only printer. 'preview' is never resolved — nothing dials."""
    return TSCLabelPrinter(ip_address="preview")


def catalog_variant_skus():
    """Every variant SKU the catalog can express.

    A pattern only pairs with a series whose braid matches its fabric_type
    (rayon patterns on the rayon series, cotton on cotton), which is how the
    real product grid is built.
    """
    skus = []
    for series in all_series():
        braid = (series.get("braid_material") or "").lower()
        for pattern in all_patterns():
            if pattern.get("fabric_type") != braid:
                continue
            for length in series["lengths"]:
                for conn in series["connectors"]:
                    sku = format_variant_sku(
                        group_sku=pattern["code"], prefix=series["sku_prefix"],
                        length=length, connector_code=conn.get("code") or "",
                    )
                    skus.append(sku)
    return skus


def elements(tspl_bytes):
    """Element boxes from rendered TSPL: (label, x, y, w, h)."""
    txt = tspl_bytes.decode("latin-1")
    out = []
    for m in _TEXT_RE.finditer(txt):
        x, y = int(m.group(1)), int(m.group(2))
        cw, ch = _FONT[m.group(3)]
        xm, ym = int(m.group(4)), int(m.group(5))
        text = m.group(6)
        out.append((f"text {text!r}", x, y, len(text) * cw * xm, ch * ym))
    for m in _BAR_RE.finditer(txt):
        x, y, w, h = (int(g) for g in m.groups())
        out.append(("rule", x, y, w, h))
    return out


# --------------------------------------------------------------------------
# describe_variant
# --------------------------------------------------------------------------

def test_describe_variant_catalog():
    d = describe_variant("SC-20GL")
    assert d["kind"] == "catalog"
    assert d["length"] == "20"
    assert d["connector"] == "TS-TS"
    assert d["cable_type"] == "Instrument"
    # The printed rows, top to bottom.
    assert d["brand_line"] == "Sundial Audio Studio Series"
    assert d["pattern"] == "Goldline"
    assert d["spec_line"] == "20' Instrument Cable"
    assert d["connector_label"] == "TS-TS"
    # The core cable rides on the connector row: the description now prints
    # at font "2", too large to carry both (110 characters against 96).
    assert d["connector_line"] == "TS-TS - Canare GS-6"
    assert d["headline"] == "Studio Classic - Goldline"
    assert d["detail"] == "Black rayon braid with gold tracer"
    assert d["sku"] == "SC-20GL"


def test_describe_variant_right_angle():
    d = describe_variant("TC-15HP-R")
    assert d["connector"] == "RA-TS"
    assert d["cable_type"] == "Instrument"
    # Both ends really are TS, one of them angled — so the product-facing
    # designation says so rather than inventing a second pair name.
    assert d["connector_label"] == "TS-TS Right Angle"
    assert d["headline"] == "Tour Classic - Houndstooth Putty"


def test_describe_variant_mic_says_nothing_about_xlr_gender():
    """An XLR cable is always male to one end and female to the other."""
    d = describe_variant("TV-12NJ")
    assert d["cable_type"] == "Microphone"
    assert d["connector_label"] == "XLR-XLR"
    assert "male" not in d["connector_label"].lower()
    assert d["spec_line"] == "12' Microphone Cable"


def test_retail_family_is_coarser_than_product_line():
    """The boxes are generic Studio / Touring; the pattern is a front sticker
    and the spec line already says Instrument or Microphone, so the brand line
    does not repeat 'Vocal Classic'."""
    assert describe_variant("SV-1PW")["brand_line"] == (
        "Sundial Audio Studio Series")
    assert describe_variant("TV-3EH")["brand_line"] == (
        "Sundial Audio Touring Series")


def test_every_series_declares_a_retail_family():
    """Without one the brand line falls back to the full product_line, which
    is both redundant and too long for the row."""
    missing = [s["sku_prefix"] for s in all_series()
               if not s.get("retail_family")]
    assert not missing, (
        f"add retail_family to {missing} in catalog/cable_lines.yaml")


def test_describe_variant_ltd_names_the_edition():
    d = describe_variant("SC-12-LTD-PHISH26-R")
    assert d["kind"] == "ltd"
    assert d["pattern"] is None
    assert d["headline"] == "Studio Classic - PHISH26"
    # No pattern description, so the detail falls back to the braid material.
    assert d["detail"] == "Rayon braid"


def test_describe_variant_misc_has_no_length_or_connector():
    d = describe_variant("SC-MISC-42")
    assert d["kind"] == "misc"
    assert d["length"] is None
    assert d["connector"] is None
    assert d["headline"] == "Studio Classic"


@pytest.mark.parametrize("bad", ["", None, "garbage", "SC", "20GL", "SC-20"])
def test_describe_variant_rejects_junk(bad):
    assert describe_variant(bad) is None


def test_every_catalog_connector_has_a_cable_type():
    """A series added with an unmapped connector would print no type at all —
    losing half the glance line."""
    missing = set()
    for series in all_series():
        for conn in series.get("connectors", []):
            display = conn.get("display")
            if retail_cable_type(display)["type"] is None:
                missing.add((series["sku_prefix"], display))
    assert not missing, (
        f"No RETAIL_CABLE_TYPES entry for {sorted(missing)} — add one "
        f"in greenlight/cable_config.py"
    )


def test_retail_cable_type_handles_an_unknown_connector():
    for unknown in ("", None, "SPEAKON-SPEAKON"):
        assert retail_cable_type(unknown) == {"type": None, "label": None}


def test_cable_types_avoid_the_inch_quote():
    """TSPL has no escape for `\"`, and the templates swap it for `'` — which
    would silently turn 1/4\" into 1/4', i.e. feet. Feet use the prime."""
    for key, entry in RETAIL_CABLE_TYPES.items():
        for field in ("type", "label"):
            assert '"' not in entry[field], (
                f"{key} {field} contains a double quote")


def test_cable_types_say_nothing_that_cannot_be_otherwise():
    """A mic cable is always male to one end and female to the other."""
    for key, entry in RETAIL_CABLE_TYPES.items():
        assert "male" not in entry["label"].lower(), (
            f"{key}: XLR gender is never a choice — drop it from "
            f"{entry['label']!r}")


def test_font_advance_table_matches_the_tests(printer):
    """The bounds checks here only mean anything if they use the same advance
    the template lays out with."""
    assert {f: w for f, (w, _h) in _FONT.items()} == printer.FONT_ADVANCE


def test_cable_types_fit_the_spec_row():
    """The type goes inside "25' Instrument Cable" on the font "4" row, which
    holds 22 characters. The longest length and " Cable" spend 10 of them."""
    printer = TSCLabelPrinter(ip_address="preview")
    row_chars = ((printer.label_width_dots - 2 * printer.SHELF_X_LEFT)
                 // printer.FONT_ADVANCE["4"])
    longest_length = max(
        (describe_variant(s)["length"] for s in catalog_variant_skus()),
        key=len)
    budget = row_chars - len(f"{longest_length}' ") - len(" Cable")
    too_long = {k: v["type"] for k, v in RETAIL_CABLE_TYPES.items()
                if len(v["type"]) > budget}
    assert not too_long, (
        f"these push the spec row past {row_chars} chars: {too_long}")


def test_no_cable_type_restates_a_default():
    """Straight-to-straight is the instrument default and XLR male-to-female
    the mic one, so no label spells either out — only the right-angle variant
    qualifies itself."""
    for key, entry in RETAIL_CABLE_TYPES.items():
        label = entry["label"].lower()
        assert "straight/straight" not in label, (
            f"{key}: straight-to-straight is the default — don't print it")
        assert "female" not in label, (
            f"{key}: XLR gender is never a choice — drop it")


# --------------------------------------------------------------------------
# _tspl_safe
# --------------------------------------------------------------------------

def test_tspl_safe_folds_catalog_en_dashes():
    assert _tspl_safe("TS–TS") == "TS-TS"


def test_tspl_safe_neutralizes_quotes_and_non_ascii():
    assert _tspl_safe('a "b" c') == "a 'b' c"
    # é has no ASCII fold and is dropped; the em-dash folds to '-'
    # and the prime to an apostrophe (Shopify titles use it for feet).
    assert _tspl_safe("café — 20′") == "caf - 20'"


@pytest.mark.parametrize("empty", ["", None])
def test_tspl_safe_handles_empty(empty):
    assert _tspl_safe(empty) == ""


# --------------------------------------------------------------------------
# shelf_label rendering
# --------------------------------------------------------------------------

def test_shelf_label_contains_the_chosen_content(printer):
    txt = printer._generate_shelf_label_tspl(
        describe_variant("SC-20GL")).decode("latin-1")
    assert 'SIZE 76.2 mm, 25.4 mm' in txt
    assert ',"3",0,1,1,"Sundial Audio Studio Series"' in txt   # 1. brand
    assert ',"3",0,1,1,"Goldline"' in txt                      # 2. pattern
    assert ''',"4",0,1,1,"20' Instrument Cable"''' in txt      # 3. spec
    assert ',"2",0,1,1,"TS-TS - Canare GS-6"' in txt           # 4. connector
    assert '"SC-20GL"' in txt                                  # 5. corner SKU
    assert txt.rstrip().endswith("PRINT 1,1")


def test_shelf_label_rows_run_top_to_bottom_in_order(printer):
    """Reading order is layout order: brand, pattern, spec, connector,
    then the description."""
    data = describe_variant("SC-20GL")
    txt = printer._generate_shelf_label_tspl(data).decode("latin-1")
    ys = {m.group(6): int(m.group(2)) for m in _TEXT_RE.finditer(txt)}
    seq = [ys[data[key]] for key, _f, _w in _ROWS]
    assert seq == sorted(seq), f"rows out of order: {seq}"
    assert ys[data["sku"]] > seq[-1], "SKU is not below the rows above"


def test_shelf_label_spec_row_is_the_largest(printer):
    """It carries the buying decision, so nothing on the label outranks it."""
    txt = printer._generate_shelf_label_tspl(
        describe_variant("SC-20GL")).decode("latin-1")
    fonts = {m.group(6): m.group(3) for m in _TEXT_RE.finditer(txt)}
    assert fonts["20' Instrument Cable"] == "4"
    assert all(f <= "4" for f in fonts.values()), fonts


def test_shelf_label_sku_sits_below_every_other_row(printer):
    """It belongs in the bottom corner, not partway up the label."""
    txt = printer._generate_shelf_label_tspl(
        describe_variant("SC-20GL")).decode("latin-1")
    ys = {m.group(6): int(m.group(2)) for m in _TEXT_RE.finditer(txt)}
    sku_y = ys.pop("SC-20GL")
    assert sku_y > max(ys.values()), f"SKU at y={sku_y}, rows at {ys}"


def test_shelf_label_sku_has_a_wider_right_margin_than_the_left_gutter(printer):
    """It sits alone in the corner; a tight margin there reads as a crop
    rather than as a choice."""
    txt = printer._generate_shelf_label_tspl(
        describe_variant("SC-20GL")).decode("latin-1")
    m = next(m for m in _TEXT_RE.finditer(txt) if m.group(6) == "SC-20GL")
    right_gap = printer.label_width_dots - (
        int(m.group(1)) + 7 * printer.FONT_ADVANCE["2"])
    assert right_gap > printer.SHELF_X_LEFT
    assert right_gap == printer.SHELF_X_LEFT + printer.SHELF_X_SKU_PAD


def test_shelf_label_prints_no_braid_description(printer):
    """The pattern row says the same thing in one word, and at up to three
    rows the description was the biggest thing on a label that read as a wall
    of text. `describe_variant` still returns the copy as `detail`; the label
    just doesn't print it."""
    data = describe_variant("SC-20GL")
    assert data["detail"] == "Black rayon braid with gold tracer"
    txt = printer._generate_shelf_label_tspl(data).decode("latin-1")
    assert data["detail"] not in txt
    assert "rayon" not in txt


def test_shelf_label_has_six_rows_with_room_between_them(printer):
    """Six rows, not eight. The gap between them is the whole point of
    dropping the description, so hold a floor under it."""
    boxes = elements(printer._generate_shelf_label_tspl(
        describe_variant("SC-20GL")))
    rows = sorted(boxes, key=lambda b: b[2])
    assert len(rows) == 6, [b[0] for b in rows]

    gaps = [b[2] - (a[2] + a[4]) for a, b in zip(rows, rows[1:])]
    assert min(gaps) >= 6, f"rows too tight: {gaps}"
    # And the label still ends with a margin rather than a crop.
    last = rows[-1]
    assert printer.label_height_dots - (last[2] + last[4]) >= 8


def test_shelf_label_sku_sits_on_its_own_row(printer):
    """Sharing the connector's row works for most variants but leaves the
    longest connector line ending 5 dots short of the SKU -- and a third of
    the catalog is right-angle. Check the worst case has a real gap."""
    worst = max((s for s in catalog_variant_skus()
                 if describe_variant(s)["connector"] == "RA-TS"),
                key=lambda s: len(describe_variant(s)["connector_line"]))
    boxes = elements(printer._generate_shelf_label_tspl(
        describe_variant(worst)))
    conn = next(b for b in boxes if "Right Angle" in b[0])
    sku = next(b for b in boxes if worst in b[0])
    assert sku[2] > conn[2] + conn[4], f"{worst}: SKU shares the connector row"
def test_shelf_label_carries_no_barcode(printer):
    """By design: the UPC on the back of the box is what a POS scans."""
    txt = printer._generate_shelf_label_tspl(
        describe_variant("SC-20GL")).decode("latin-1")
    assert "BARCODE" not in txt
    assert "BITMAP" not in txt


def test_shelf_label_omits_missing_fields(printer):
    """A MISC build has no length or connector; the label just drops them."""
    tspl = printer._generate_shelf_label_tspl(describe_variant("SC-MISC-42"))
    txt = tspl.decode("latin-1")
    assert ',"4",0,1,1' not in txt         # no spec row at all
    assert '"Sundial Audio Studio Series"' in txt
    assert txt.rstrip().endswith("PRINT 1,1")


def test_shelf_label_prints_the_product_facing_connector_name(printer):
    """The connector row is deliberately the engineering pair name -- but the
    PRODUCT-facing form of it. A right-angle cable reads "TS-TS Right Angle",
    so the raw 'RA-TS' shorthand must never reach the label."""
    for sku in ("SC-20GL", "TC-15HP-R", "TV-12NJ"):
        data = describe_variant(sku)
        txt = printer._generate_shelf_label_tspl(data).decode("latin-1")
        assert f'"{data["connector_line"]}"' in txt
        assert data["connector_label"] in data["connector_line"]
        assert data["cable_type"] in txt
    angled = describe_variant("TC-15HP-R")
    txt = printer._generate_shelf_label_tspl(angled).decode("latin-1")
    assert '"RA-TS"' not in txt, "raw RA-TS shorthand leaked onto the label"


def test_shelf_label_uses_the_prime_for_feet_and_no_inch_mark(printer):
    """TSPL cannot escape a double quote, so an inch mark is unprintable; a
    prime for feet is fine and is what the spec row uses."""
    txt = printer._generate_shelf_label_tspl(
        describe_variant("SC-20GL")).decode("latin-1")
    spec = next(m.group(6) for m in _TEXT_RE.finditer(txt)
                if m.group(3) == "4")
    assert spec.startswith("20'")


def test_shelf_label_right_angle_differs_only_in_the_connector_row(printer):
    straight = printer._generate_shelf_label_tspl(
        describe_variant("SC-20GL")).decode("latin-1")
    angled = printer._generate_shelf_label_tspl(
        describe_variant("SC-20GL-R")).decode("latin-1")
    assert '"TS-TS - Canare GS-6"' in straight
    assert "Right Angle" not in straight
    assert '"TS-TS Right Angle - Canare GS-6"' in angled
    for shared in ("Sundial Audio Studio Series", "20' Instrument Cable",
                   "Goldline"):
        assert shared in straight and shared in angled


def test_every_catalog_connector_line_fits_its_row(printer):
    """The core cable rides on this row, so it is the one most likely to
    outgrow itself when a series with a longer core cable is added."""
    max_chars = ((printer.label_width_dots - 2 * printer.SHELF_X_LEFT)
                 // printer.FONT_ADVANCE["2"])
    too_long = {}
    for sku in catalog_variant_skus():
        line = describe_variant(sku)["connector_line"]
        if len(line) > max_chars:
            too_long[line] = len(line)
    assert not too_long, (
        f"connector rows clip (limit {max_chars} chars): {too_long}")


def test_shelf_label_falls_back_to_the_bare_connector_label(printer):
    """A caller without the composed row still gets the connector named."""
    txt = printer._generate_shelf_label_tspl(
        {"connector_label": "TS-TS Right Angle"}).decode("latin-1")
    assert '"TS-TS Right Angle"' in txt


def test_shelf_label_falls_back_to_the_headline_for_the_pattern(printer):
    """A caller without the pattern split out still gets a third line."""
    txt = printer._generate_shelf_label_tspl(
        {"headline": "Studio Classic - Goldline"}).decode("latin-1")
    assert '"Studio Classic - Goldline"' in txt


def test_shelf_label_clips_an_overlong_spec_row(printer):
    txt = printer._generate_shelf_label_tspl(
        {"spec_line": "x" * 99}).decode("latin-1")
    spec = next(m.group(6) for m in _TEXT_RE.finditer(txt)
                if m.group(3) == "4")
    usable = printer.label_width_dots - 2 * printer.SHELF_X_LEFT
    assert len(spec) == usable // printer.FONT_ADVANCE["4"]


def test_shelf_label_survives_empty_data(printer):
    """Nothing but the frame — must not raise or emit a malformed command."""
    txt = printer._generate_shelf_label_tspl({}).decode("latin-1")
    assert "TEXT" not in txt
    assert "BAR " in txt
    assert txt.rstrip().endswith("PRINT 1,1")


def test_shelf_label_shrinks_the_sku_font_when_long(printer):
    """A long LTD SKU drops to font "1" so it still fits its corner."""
    long_sku = "SC-12-LTD-PHISH26-R"
    txt = printer._generate_shelf_label_tspl(
        describe_variant(long_sku)).decode("latin-1")
    m = next(m for m in _TEXT_RE.finditer(txt) if m.group(6) == long_sku)
    assert m.group(3) == "1"


def test_shelf_label_quotes_in_input_cannot_break_the_tspl(printer):
    """An unescaped `"` would terminate the TEXT command early and leave the
    rest of the string to be read as TSPL."""
    txt = printer._generate_shelf_label_tspl({
        "headline": 'Studio "Classic"', "detail": 'PRINT 99"',
    }).decode("latin-1")
    for line in txt.split("\r\n"):
        if line.startswith("TEXT"):
            assert _TEXT_RE.fullmatch(line), f"malformed TEXT command: {line}"
    assert "PRINT 99" not in txt.replace("PRINT 99'", "")


# --------------------------------------------------------------------------
# The sweep: every catalog variant must fit the label
# --------------------------------------------------------------------------

@pytest.mark.parametrize("sku", catalog_variant_skus())
def test_shelf_label_fits_every_catalog_variant(printer, sku):
    data = describe_variant(sku)
    assert data is not None, f"{sku} did not parse"
    tspl = printer._generate_shelf_label_tspl(data)

    # The TE210's bitmap fonts render a single-byte codepage.
    assert all(b < 127 for b in tspl), f"{sku}: non-ASCII byte in the TSPL"

    boxes = elements(tspl)
    assert boxes, f"{sku}: rendered nothing"

    w, h = printer.label_width_dots, printer.label_height_dots
    for label, x, y, bw, bh in boxes:
        assert x >= 2 and y >= 2, f"{sku}: {label} starts off-label at ({x},{y})"
        assert x + bw <= w, (f"{sku}: {label} runs {x + bw - w} dots past the "
                             f"right edge")
        assert y + bh <= h, (f"{sku}: {label} runs {y + bh - h} dots past the "
                             f"bottom edge")

    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            overlaps = (a[1] < b[1] + b[3] and b[1] < a[1] + a[3]
                        and a[2] < b[2] + b[4] and b[2] < a[2] + a[4])
            assert not overlaps, f"{sku}: {a[0]} overlaps {b[0]}"


@pytest.mark.parametrize("key,font,char_w", _ROWS)
def test_every_catalog_line_fits_its_row(printer, key, font, char_w):
    """Each line is clipped, not wrapped — the vertical budget is spoken for,
    so a line that outgrows its row would have to push another off the label.
    A name that doesn't fit must be caught here, not on the sticker."""
    max_chars = (printer.label_width_dots - 2 * printer.SHELF_X_LEFT) // char_w
    too_long = {}
    for sku in catalog_variant_skus():
        val = describe_variant(sku)[key] or ""
        if len(val) > max_chars:
            too_long[val] = len(val)
    assert not too_long, (
        f"{key} clips at font {font} (limit {max_chars} chars): {too_long} — "
        f"shorten the catalog name rather than growing the label")


def test_sweep_actually_covers_the_catalog():
    """Guard the guard: a broken pairing rule would make the sweep vacuous."""
    skus = catalog_variant_skus()
    assert len(skus) > 150, f"only {len(skus)} variants swept — pairing broke?"
    assert len(set(skus)) == len(skus), "duplicate SKUs in the sweep"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
