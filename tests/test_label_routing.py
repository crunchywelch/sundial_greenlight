#!/usr/bin/env python3
"""Tests that every label reaches the printer holding its stock.

Each roll has its own printer. The failure these guard against is quiet: a 2"
box label sent to the 1" roll wastes labels and leaves that printer's
remembered SIZE wrong. And a failure on one printer must not cost the labels
bound for the other.

Run: pytest tests/test_label_routing.py  (no DB, no Shopify, no printer)
"""

import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenlight.hardware import tsc_label_printer as tsc
from greenlight.hardware.interfaces import HardwareManager, PrintJob
from greenlight.hardware.tsc_label_printer import (
    BOX_STOCK_MM, CABLE_ROLL_MM, LABEL_STOCK, MockTSCLabelPrinter, TSCLabelPrinter,
    build_label_printers, printer_host_for_stock,
)
from greenlight.label_batch import plan_order
from greenlight.screens.order_labels import CALIBRATE_KEYS, OrderLabelPrintScreen

from test_label_batching import TEMPLATE_DATA

LINES = [{"sku": "SC-20GL", "quantity": 2, "title": "Cable"}]
UPCS = {"SC-20GL": "860012345678"}


def _mock(stock, ready=True, prints=True):
    printer = MockTSCLabelPrinter(ip_address=f"host-{stock[1]}",
                                  label_width_mm=stock[0], label_height_mm=stock[1])
    printer.initialize()
    printer.sent = []
    printer.calibrations = 0
    real_print = printer.print_labels

    def print_labels(job):
        if prints and real_print(job):
            printer.sent.append(job.template)
            return True
        return False

    def calibrate_media():
        printer.calibrations += 1
        return True

    printer.print_labels = print_labels
    printer.calibrate_media = calibrate_media
    printer.is_ready = lambda: ready
    return printer


def _run_print(printers, plan=None):
    """Run the screen's print with these printers; returns the summary text."""
    ui = mock.MagicMock()
    with mock.patch("greenlight.hardware.interfaces.hardware_manager"
                    ".get_label_printer", side_effect=lambda s: printers.get(tuple(s))):
        OrderLabelPrintScreen(ui, {})._print(
            "ADW", plan or plan_order(LINES, upc_by_sku=UPCS))
    ui.console.input.assert_not_called()     # no roll-swap prompts
    return str(ui.layout.__getitem__.return_value.update.call_args_list[0].args[0]
               .renderable)


def test_each_host_serves_its_own_stock():
    assert printer_host_for_stock(CABLE_ROLL_MM) == tsc.TSC_1IN_PRINTER_IP
    assert printer_host_for_stock(BOX_STOCK_MM) == tsc.TSC_2IN_PRINTER_IP
    assert printer_host_for_stock((76.2, 38.1)) is None


def test_default_hosts_are_distinct():
    """A shared default would quietly send box labels to the 1in roll."""
    from greenlight.config import TSC_1IN_PRINTER_IP, TSC_2IN_PRINTER_IP
    assert TSC_1IN_PRINTER_IP != TSC_2IN_PRINTER_IP


@pytest.mark.parametrize("mock_printers", [True, False])
def test_build_gives_each_printer_its_stock_and_host(mock_printers):
    printers = build_label_printers(mock=mock_printers)
    assert set(printers) == {CABLE_ROLL_MM, BOX_STOCK_MM}
    for stock, printer in printers.items():
        assert (printer.label_width_mm, printer.label_height_mm) == stock
        assert printer.ip_address == printer_host_for_stock(stock)


def test_an_unset_two_inch_printer_is_absent_not_the_one_inch():
    with mock.patch.object(tsc, "TSC_2IN_PRINTER_IP", ""):
        printers = build_label_printers(mock=True)
    assert set(printers) == {CABLE_ROLL_MM}


def test_manager_resolves_by_stock_and_has_no_default():
    manager = HardwareManager()
    one, two = _mock(CABLE_ROLL_MM), _mock(BOX_STOCK_MM)
    manager.set_hardware(label_printers={CABLE_ROLL_MM: one, BOX_STOCK_MM: two})
    assert manager.get_label_printer(CABLE_ROLL_MM) is one
    assert manager.get_label_printer(list(BOX_STOCK_MM)) is two
    assert manager.get_label_printer((76.2, 38.1)) is None
    with pytest.raises(TypeError):
        manager.get_label_printer()


@pytest.mark.parametrize("printer_class", [TSCLabelPrinter, MockTSCLabelPrinter])
@pytest.mark.parametrize("template,stock", LABEL_STOCK.items())
def test_a_printer_refuses_any_template_for_the_other_roll(printer_class, template, stock):
    other = BOX_STOCK_MM if stock == CABLE_ROLL_MM else CABLE_ROLL_MM
    printer = printer_class("preview", label_width_mm=other[0], label_height_mm=other[1])
    printer.connected = True
    printer._send_tspl_commands = mock.Mock(return_value=True)
    job = PrintJob(template=template, data=dict(TEMPLATE_DATA[template]), quantity=1)
    assert printer.print_labels(job) is False
    printer._send_tspl_commands.assert_not_called()


@pytest.mark.parametrize("template,stock", LABEL_STOCK.items())
def test_a_printer_accepts_every_template_for_its_own_roll(template, stock):
    printer = TSCLabelPrinter("preview", label_width_mm=stock[0], label_height_mm=stock[1])
    printer.connected = True
    printer._send_tspl_commands = mock.Mock(return_value=True)
    job = PrintJob(template=template, data=dict(TEMPLATE_DATA[template]), quantity=1)
    assert printer.print_labels(job) is True
    printer._send_tspl_commands.assert_called_once()


def test_an_order_splits_across_printers_with_no_prompts_or_calibration():
    one, two = _mock(CABLE_ROLL_MM), _mock(BOX_STOCK_MM)
    summary = _run_print({CABLE_ROLL_MM: one, BOX_STOCK_MM: two})
    assert sorted(one.sent) == ["prop65_label", "shelf_label"]
    assert two.sent == ["box_label"]
    assert one.calibrations == two.calibrations == 0
    assert "1\" printer: sent 4" in summary
    assert "2\" printer: sent 2" in summary


def test_a_dead_printer_does_not_stop_the_other():
    one, two = _mock(CABLE_ROLL_MM, ready=False), _mock(BOX_STOCK_MM)
    summary = _run_print({CABLE_ROLL_MM: one, BOX_STOCK_MM: two})
    assert one.sent == [] and two.sent == ["box_label"]
    assert "not responding at host-25.4" in summary
    assert "4 label(s) not sent" in summary

    one, two = _mock(CABLE_ROLL_MM), _mock(BOX_STOCK_MM, ready=False)
    summary = _run_print({CABLE_ROLL_MM: one, BOX_STOCK_MM: two})
    assert sorted(one.sent) == ["prop65_label", "shelf_label"] and two.sent == []
    assert "2 label(s) not sent" in summary


def test_an_unconfigured_printer_is_reported_and_nothing_reroutes():
    one = _mock(CABLE_ROLL_MM)
    summary = _run_print({CABLE_ROLL_MM: one})
    assert "box_label" not in one.sent
    assert "2\" printer: not configured" in summary


def test_a_failure_part_way_says_how_many_were_sent():
    one, two = _mock(CABLE_ROLL_MM), _mock(BOX_STOCK_MM, prints=False)
    summary = _run_print({CABLE_ROLL_MM: one, BOX_STOCK_MM: two})
    assert "0 of 2 label(s) sent" in summary
    assert "1\" printer: sent 4" in summary


def test_calibrate_keys_reach_only_the_named_printer():
    one, two = _mock(CABLE_ROLL_MM), _mock(BOX_STOCK_MM)
    printers = {CABLE_ROLL_MM: one, BOX_STOCK_MM: two}
    screen = OrderLabelPrintScreen(mock.MagicMock(), {})
    with mock.patch("greenlight.hardware.interfaces.hardware_manager"
                    ".get_label_printer", side_effect=lambda s: printers.get(tuple(s))):
        assert "calibrating" in screen._calibrate(CALIBRATE_KEYS["c2"])
    assert (one.calibrations, two.calibrations) == (0, 1)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
