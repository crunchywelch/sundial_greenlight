#!/usr/bin/env python3
"""Tests for calibrating a printer's media sensor, and its registration.

Every template sends SIZE and GAP, but those only say how big a label is,
not where the next one starts. After loading a roll the printer can be
registered to the wrong gaps and the image lands off the label -- on the 1"
side label the SKU, the bottom row, is the first thing lost. So calibrating
runs GAPDETECT, on request only, because it spends labels.

Run: pytest tests/test_media_calibration.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenlight.hardware.tsc_label_printer import (
    BOX_STOCK_MM, CABLE_ROLL_MM, TSCLabelPrinter,
)


def _printer(sent, stock=BOX_STOCK_MM, ok=True):
    printer = TSCLabelPrinter("127.0.0.1", label_width_mm=stock[0],
                              label_height_mm=stock[1])
    printer.connected = True

    def send(tspl, *_):
        sent.append(tspl.decode("latin-1") if isinstance(tspl, bytes) else tspl)
        return ok
    printer._send_tspl_commands = send
    return printer


def test_calibrate_sends_this_printers_size_gap_and_gapdetect():
    sent = []
    assert _printer(sent).calibrate_media()
    (tspl,) = sent
    assert "SIZE 76.2 mm, 50.8 mm" in tspl
    assert "GAP 2.0 mm, 2.0 mm" in tspl
    assert "SHIFT 0" in tspl
    assert "GAPDETECT" in tspl

    sent = []
    assert _printer(sent, CABLE_ROLL_MM).calibrate_media()
    assert "SIZE 76.2 mm, 25.4 mm" in sent[0]


def test_a_failed_calibration_reports_failure():
    assert not _printer([], ok=False).calibrate_media()


# Every template, from the table test_label_batching.py already keeps.
from test_label_batching import TEMPLATE_DATA  # noqa: E402
from greenlight.hardware.tsc_label_printer import stock_for_template  # noqa: E402


def _header_lines(tspl):
    lines = tspl.decode("latin-1").split("\r\n")
    return lines[:lines.index("CLS") + 1]


def test_every_template_sends_its_stocks_registration():
    """SHIFT persists in the printer, so a template that doesn't send its own
    inherits whatever the last job -- or a tuning session -- left behind."""
    printer = TSCLabelPrinter("preview")
    for template, method in TSCLabelPrinter.TEMPLATES.items():
        stock = stock_for_template(template)
        reg = TSCLabelPrinter.MEDIA_REGISTRATION[stock]
        header = _header_lines(getattr(printer, method)(dict(TEMPLATE_DATA[template])))
        assert f"SIZE {stock[0]:.1f} mm, {stock[1]:.1f} mm" in header, template
        assert (f"GAP {TSCLabelPrinter.GAP_MM:.1f} mm, "
                f"{reg['gap_offset_mm']:.1f} mm") in header, template
        assert f"SHIFT {reg['shift']}" in header, template


def test_one_inch_registration_is_the_measured_one():
    """GAP 2,2 and no shift: what the cable labels printed with for months,
    re-measured 2026-10-08. Changing it moves every 1" label."""
    assert TSCLabelPrinter.MEDIA_REGISTRATION[CABLE_ROLL_MM] == {
        "gap_offset_mm": 2.0, "shift": 0}
