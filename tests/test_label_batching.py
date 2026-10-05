#!/usr/bin/env python3
"""Tests for the pieces a batch print run needs: copies, and label stock.

Two things were missing before a wholesale order could be printed in one go.

`PrintJob.quantity` was accepted, logged, and ignored: eight of the nine
templates hardcoded `PRINT 1`, while `print_labels()` reported having printed
`print_job.quantity`. So a job for 12 labels produced one and claimed twelve,
and every caller that wanted N had to loop -- opening N sockets.

And no template declared what stock it needs, so grouping a run by stock (one
roll swap instead of one per label) or routing to a second printer would each
have had to hardcode the knowledge.

Run: pytest tests/test_label_batching.py  (no DB, no Shopify, no printer)
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenlight.hardware.interfaces import PrintJob
from greenlight.hardware.tsc_label_printer import (
    BOX_STOCK_MM, CABLE_ROLL_MM, LABEL_STOCK, MockTSCLabelPrinter,
    TSCLabelPrinter, stock_for_template,
)

_PRINT_RE = re.compile(r"PRINT (\d+),(\d+)")

# Minimal data that renders each template without raising. box_label refuses
# an invalid GTIN, so it needs a real one.
TEMPLATE_DATA = {
    "cable_label":        {"sku": "SC-20GL", "serial_number": "1001"},
    "registration_label": {"registration_code": "ABCD-1234",
                           "serial_number": "1001", "sku": "SC-20GL"},
    "wire_label":         {"product_title": "Lamp Cord", "sku": "W-1"},
    "barcode_label":      {"serial_number": "1001", "sku": "SC-20GL"},
    "bin_label":          {"sku": "SC-20GL", "title": "Studio Classic"},
    "shelf_label":        {"brand_line": "Sundial Audio Studio Series",
                           "spec_line": "20' Instrument Cable"},
    "box_label":          {"upc": "036000291452", "sku": "SC-20GL"},
    "text_label":         {"lines": ["hello"], "text": "hello"},
    "prop65_label":       {},
}


@pytest.fixture(scope="module")
def printer():
    """A generator-only printer. 'preview' is never resolved — nothing dials."""
    return TSCLabelPrinter(ip_address="preview")


# --------------------------------------------------------------------------
# Copies
# --------------------------------------------------------------------------

@pytest.mark.parametrize("template", sorted(TEMPLATE_DATA))
def test_every_template_honours_quantity(printer, template):
    """`PRINT m,n` -- m sets of n copies -- so the printer does the repeat and
    one connection prints the whole lot."""
    data = dict(TEMPLATE_DATA[template], quantity=12)
    tspl = getattr(printer, TSCLabelPrinter.TEMPLATES[template])(data)
    m = _PRINT_RE.search(tspl.decode("latin-1"))
    assert m, f"{template}: no PRINT command"
    assert int(m.group(1)) == 12, f"{template}: printed {m.group(1)} not 12"


@pytest.mark.parametrize("template", sorted(TEMPLATE_DATA))
def test_every_template_defaults_to_one_copy(printer, template):
    tspl = getattr(printer, TSCLabelPrinter.TEMPLATES[template])(
        dict(TEMPLATE_DATA[template]))
    m = _PRINT_RE.search(tspl.decode("latin-1"))
    assert int(m.group(1)) == 1


@pytest.mark.parametrize("bad", [0, -5, None, "", "abc", 1.7])
def test_a_junk_quantity_floors_at_one(printer, bad):
    """Never print zero labels for a job someone asked for, and never raise
    in a template over a bad count."""
    assert printer._print_quantity({"quantity": bad}) >= 1


def test_print_job_quantity_reaches_the_template(monkeypatch, printer):
    """The path that was broken: PrintJob.quantity -> the PRINT command."""
    sent = {}
    monkeypatch.setattr(printer, "_send_tspl_commands",
                        lambda tspl: sent.setdefault("tspl", tspl) or True)
    printer.connected = True
    assert printer.print_labels(PrintJob(
        template="shelf_label", data=TEMPLATE_DATA["shelf_label"], quantity=7))
    m = _PRINT_RE.search(sent["tspl"].decode("latin-1"))
    assert int(m.group(1)) == 7


def test_print_labels_does_not_mutate_the_caller_data(monkeypatch, printer):
    """It injects the quantity into the data dict, so it must copy first."""
    monkeypatch.setattr(printer, "_send_tspl_commands", lambda tspl: True)
    printer.connected = True
    data = {"sku": "SC-20GL", "title": "Studio Classic"}
    printer.print_labels(PrintJob(template="bin_label", data=data, quantity=4))
    assert "quantity" not in data


def test_explicit_data_quantity_wins_over_the_job(monkeypatch, printer):
    """`setdefault` -- a caller that put the count in data meant it. This is
    how print_prop65.py has always passed it."""
    sent = {}
    monkeypatch.setattr(printer, "_send_tspl_commands",
                        lambda tspl: sent.setdefault("tspl", tspl) or True)
    printer.connected = True
    printer.print_labels(PrintJob(
        template="prop65_label", data={"quantity": 3}, quantity=99))
    m = _PRINT_RE.search(sent["tspl"].decode("latin-1"))
    assert int(m.group(1)) == 3


# --------------------------------------------------------------------------
# Stock, and the dispatch table
# --------------------------------------------------------------------------

def test_every_template_declares_its_stock():
    """A template wired up without a stock entry would be unroutable and
    ungroupable, and the omission would be silent."""
    assert set(LABEL_STOCK) == set(TSCLabelPrinter.TEMPLATES)


def test_the_test_data_covers_every_template():
    """Guard the guard: a new template must be exercised above, not skipped."""
    assert set(TEMPLATE_DATA) == set(TSCLabelPrinter.TEMPLATES)


def test_only_the_box_label_wants_the_tall_stock():
    """It is the one that needs 2in: a UPC-A only renders at whole-dot module
    widths, and 1in forces it to the 75% thermal floor."""
    tall = {t for t, s in LABEL_STOCK.items() if s == BOX_STOCK_MM}
    assert tall == {"box_label"}
    assert stock_for_template("shelf_label") == CABLE_ROLL_MM


def test_box_label_defaults_match_the_stock_table():
    """Two copies of the same dimensions would drift."""
    assert (TSCLabelPrinter.BOX_LABEL_WIDTH_MM,
            TSCLabelPrinter.BOX_LABEL_HEIGHT_MM) == BOX_STOCK_MM


def test_stock_for_an_unknown_template_is_none():
    assert stock_for_template("not_a_template") is None


def test_grouping_a_mixed_run_by_stock():
    """What a wholesale order needs: all the 2in work, one roll swap, then
    all the 1in work."""
    run = ["shelf_label", "box_label", "registration_label", "box_label",
           "shelf_label"]
    groups = {}
    for t in run:
        groups.setdefault(stock_for_template(t), []).append(t)
    assert len(groups) == 2, "a mixed run should need exactly one swap"
    assert groups[BOX_STOCK_MM] == ["box_label", "box_label"]


# --------------------------------------------------------------------------
# The mock must agree with the real printer
# --------------------------------------------------------------------------

def test_mock_accepts_exactly_the_real_templates():
    """The mock's own if/elif chain had silently fallen behind, missing
    box_label and shelf_label while the real printer had both."""
    mock = MockTSCLabelPrinter()
    mock.initialize()
    for template in TSCLabelPrinter.TEMPLATES:
        assert mock.print_labels(PrintJob(template=template, data={}, quantity=1))


def test_mock_rejects_an_unknown_template():
    mock = MockTSCLabelPrinter()
    mock.initialize()
    assert not mock.print_labels(
        PrintJob(template="no_such_label", data={}, quantity=1))


def test_real_printer_rejects_an_unknown_template(printer):
    printer.connected = True
    assert not printer.print_labels(
        PrintJob(template="no_such_label", data={}, quantity=1))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
