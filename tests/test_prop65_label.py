#!/usr/bin/env python3
"""Tests for the Prop 65 warning label: its words and its layout.

The words are the regulation's (27 CCR 25603(b)), not ours, so they are
pinned exactly. The layout must keep the text legal (>= 6 pt, so never font
"1"), keep www.P65Warnings.ca.gov whole, and stay on a 1" x 3" label.

Run: pytest tests/test_prop65_label.py
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenlight.hardware.tsc_label_printer import TSCLabelPrinter, prop65_warning

URL = "www.P65Warnings.ca.gov."


@pytest.mark.parametrize("endpoints, kind", [
    ("both", "a carcinogen and reproductive toxicant"),
    ("cancer", "a carcinogen"),
    ("reproductive", "a reproductive toxicant"),
])
def test_named_short_form_is_the_2025_safe_harbor_text(endpoints, kind):
    assert prop65_warning(chemical="DEHP", endpoints=endpoints) == (
        "CA WARNING", f"Can expose you to DEHP, {kind}. See {URL}")


def test_unnamed_short_form_is_the_pre_2028_text():
    assert prop65_warning() == (
        "WARNING", f"Cancer and Reproductive Harm - {URL}")


def _texts(data):
    tspl = TSCLabelPrinter("preview")._generate_prop65_label_tspl(data)
    return re.findall(r'TEXT (\d+),(\d+),"(\d)",0,1,1,"([^"]*)"',
                      tspl.decode("latin-1"))


@pytest.mark.parametrize("data", [
    {}, {"chemical": "DEHP"}, {"chemical": "DEHP", "endpoints": "cancer"},
    {"chemical": "lead", "form": "long"},
])
def test_layout_is_legible_whole_and_on_the_label(data):
    printer = TSCLabelPrinter("preview")
    texts = _texts(data)
    assert texts
    for x, y, font, text in texts:
        x, y = int(x), int(y)
        assert font != "1", "font 1 is ~4.3 pt, under the 6 pt floor"
        assert x + len(text) * printer.FONT_ADVANCE[font] <= printer.label_width_dots - 8
        assert 4 <= y and y + printer.FONT_HEIGHT[font] <= printer.label_height_dots - 8
    joined = " ".join(t for *_, t in texts)
    assert "www.P65Warnings.ca.gov." in joined


def test_signal_word_is_bold():
    """Struck twice, a dot apart -- the fonts have no bold weight."""
    texts = _texts({"chemical": "DEHP"})
    signal = [(int(x), int(y)) for x, y, _, t in texts if t == "CA WARNING:"]
    assert len(signal) == 2
    assert signal[1][0] - signal[0][0] == 1 and signal[0][1] == signal[1][1]
