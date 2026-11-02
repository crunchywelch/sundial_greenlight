#!/usr/bin/env python3
"""Tests that every label sends its stock's registration.

SHIFT persists in the printer, so each template must send its own. Sensor
calibration itself is tools/printer/calibrate_media.py, run by hand.

Run: pytest tests/test_media_calibration.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenlight.hardware.tsc_label_printer import CABLE_ROLL_MM, TSCLabelPrinter


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
