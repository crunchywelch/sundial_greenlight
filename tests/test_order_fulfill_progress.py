#!/usr/bin/env python3
"""Tests for matching an order's cables to its line items.

This decides whether the fulfillment screen says "Order complete", and which
serials it shows against each line.

Run: pytest tests/test_order_fulfill_progress.py  (no DB, no Shopify)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenlight.screens.orders import match_cables_to_lines


def _line(sku, quantity):
    return {"sku": sku, "quantity": quantity, "title": sku}


def _cable(serial, sku):
    return {"serial_number": serial, "variant_sku": sku}


def test_each_line_gets_its_own_skus_serials_in_order():
    lines = [_line("A", 2), _line("B", 1)]
    cables = [_cable("000003", "A"), _cable("000002", "B"), _cable("000001", "A")]
    assert match_cables_to_lines(lines, cables) == [["000001", "000003"], ["000002"]]


def test_a_line_with_no_cables_is_empty():
    assert match_cables_to_lines([_line("A", 1)], []) == [[]]


def test_one_cable_cannot_complete_two_lines_of_the_same_sku():
    """It used to count for both, so the order read complete one cable short."""
    lines = [_line("A", 1), _line("A", 1)]
    assert match_cables_to_lines(lines, [_cable("000001", "A")]) == [["000001"], []]


def test_an_over_scan_stays_visible_on_the_last_line_of_its_sku():
    lines = [_line("A", 1), _line("A", 1)]
    cables = [_cable(s, "A") for s in ("000001", "000002", "000003")]
    assert match_cables_to_lines(lines, cables) == [["000001"], ["000002", "000003"]]


def test_a_cable_on_no_line_is_ignored():
    assert match_cables_to_lines([_line("A", 1)], [_cable("000001", "Z")]) == [[]]
