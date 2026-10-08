#!/usr/bin/env python3
"""Tests for re-calibrating the printer when the label roll changes.

Every template sends SIZE and GAP, but those only say how big a label is,
not where the next one starts. After a roll swap the printer stays
registered to the old stock's gaps and the image lands off the label -- on
the 1" side label the SKU, the bottom row, is the first thing lost. So a
swap has to run GAPDETECT, and a wholesale order's passes run 1" first,
since its registration labels have just gone out on that roll.

Run: pytest tests/test_media_calibration.py
"""

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenlight.hardware.tsc_label_printer import (
    BOX_STOCK_MM, CABLE_ROLL_MM, TSCLabelPrinter,
)
from greenlight.label_batch import plan_order
from greenlight.screens.order_labels import OrderLabelPrintScreen

LINES = [{"sku": "SC-20GL", "quantity": 2, "title": "Cable"}]
UPCS = {"SC-20GL": "860012345678"}


def _printer(sent, ok=True):
    printer = TSCLabelPrinter("127.0.0.1")
    printer.connected = True

    def send(tspl, *_):
        sent.append(tspl.decode("latin-1") if isinstance(tspl, bytes) else tspl)
        return ok
    printer._send_tspl_commands = send
    printer.is_ready = lambda: True
    return printer


def test_calibrate_sends_size_gap_and_gapdetect():
    sent = []
    printer = _printer(sent)
    assert printer.calibrate_media(BOX_STOCK_MM)
    (tspl,) = sent
    assert "SIZE 76.2 mm, 50.8 mm" in tspl
    assert "GAP 2.0 mm, 0 mm" in tspl
    assert "GAPDETECT" in tspl
    assert printer.loaded_stock == BOX_STOCK_MM


def test_a_failed_calibration_does_not_claim_the_stock():
    printer = _printer([], ok=False)
    assert not printer.calibrate_media(BOX_STOCK_MM)
    assert printer.loaded_stock is None


def _run_print(printer, answers):
    ui = mock.MagicMock()
    ui.console.input.side_effect = answers
    calls = []
    real_cal, real_print = printer.calibrate_media, printer.print_labels

    def cal(stock):
        calls.append(("calibrate", tuple(stock)))
        return real_cal(stock)

    def prn(job):
        calls.append(("print", job.template))
        return real_print(job)
    printer.calibrate_media, printer.print_labels = cal, prn
    plan = plan_order(LINES, upc_by_sku=UPCS)
    with mock.patch("greenlight.hardware.interfaces.hardware_manager"
                    ".get_label_printer", return_value=printer):
        OrderLabelPrintScreen(ui, {})._print("ADW", plan)
    return calls


def test_one_inch_pass_first_and_each_swap_calibrates():
    calls = _run_print(_printer([]), ["", ""])
    stocks = [c[1] for c in calls if c[0] == "calibrate"]
    assert stocks == [CABLE_ROLL_MM, BOX_STOCK_MM]
    printed = [c[1] for c in calls if c[0] == "print"]
    assert printed[-1] == "box_label"
    assert "box_label" not in printed[:-1]


def test_stock_already_calibrated_is_not_recalibrated_unless_asked():
    printer = _printer([])
    printer.loaded_stock = CABLE_ROLL_MM      # reg labels just went out on 1"
    calls = _run_print(printer, ["", ""])
    assert [c[1] for c in calls if c[0] == "calibrate"] == [BOX_STOCK_MM]

    printer = _printer([])
    printer.loaded_stock = CABLE_ROLL_MM
    calls = _run_print(printer, ["c", ""])
    assert [c[1] for c in calls if c[0] == "calibrate"] == [CABLE_ROLL_MM,
                                                             BOX_STOCK_MM]
