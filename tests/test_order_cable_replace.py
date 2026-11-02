#!/usr/bin/env python3
"""Tests for a full line on the scan screen, and replacing a cable on an order.

A cable scanned for a full line must change nothing unless the operator picks
which cable it replaces. A replacement must never lose a cable: the new one goes
on first, and the old one only comes off once it has.

Run: pytest tests/test_order_cable_replace.py  (no DB, no Shopify, no printer)
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenlight import db as db_module
from greenlight.screen_manager import NavigationAction
from greenlight.screens import orders
from greenlight.screens.orders import (
    OrderFulfillScanScreen, line_quantities, pick_cable,
)

SKU = "SC-15MB-R"
LINES = [{"sku": SKU, "quantity": 2, "title": "Cable"}]
ON_ORDER = [{"serial_number": "000916", "variant_sku": SKU},
            {"serial_number": "000917", "variant_sku": SKU}]
FULL = {"error": "line_full", "sku": SKU, "quantity": 2, "message": "full"}
OK = {"success": True, "sku": SKU}


def _run(typed, assign, wholesale=True, on_order=ON_ORDER, release=None):
    ui = MagicMock()
    ui.get_serial_number_scan_or_manual.side_effect = list(typed)
    screen = OrderFulfillScanScreen(ui, {
        "order_id": "gid://shopify/DraftOrder/1", "order_name": "#D15",
        "line_items": LINES, "scanned_cables": [],
        "selected_customer": {"id": "gid://shopify/Customer/1"},
        "company_gid": "gid://shopify/Company/1" if wholesale else None,
        "dealer_name": "Mill River" if wholesale else None,
    })
    with patch.object(orders.db, "get_cables_for_order", return_value=on_order), \
         patch.object(orders.db, "assign_cable_to_order", side_effect=assign) as assign_mock, \
         patch.object(orders.db, "unassign_cable",
                      return_value=release or {"success": True}) as release_mock, \
         patch.object(orders.db, "get_audio_cable", return_value={"sku": SKU}), \
         patch.object(orders.shopify_client, "sync_inventory_for_cable",
                      return_value=(True, None)), \
         patch.object(OrderFulfillScanScreen, "_registration_label",
                      return_value=" printed") as label_mock:
        result = screen.run()
    return result, assign_mock, release_mock, label_mock


def test_line_quantities_add_up_a_sku_on_two_lines():
    lines = [{"sku": "A", "quantity": 2}, {"sku": "B", "quantity": 1}, {"sku": "A", "quantity": 3}]
    assert line_quantities(lines) == {"A": 5, "B": 1}


def test_pick_cable_by_row_number():
    assert pick_cable("2", ON_ORDER)["serial_number"] == "000917"


def test_pick_cable_by_scanned_serial():
    assert pick_cable("000916", ON_ORDER)["serial_number"] == "000916"


def test_a_scanned_serial_is_never_mistaken_for_a_row_number():
    cables = [{"serial_number": "000916"}, {"serial_number": "000001"}]
    assert pick_cable("000001", cables)["serial_number"] == "000001"
    assert pick_cable("000002", cables) is None


def test_pick_cable_rejects_anything_else():
    assert pick_cable("3", ON_ORDER) is None
    assert pick_cable("000999", ON_ORDER) is None


def test_the_scan_passes_the_quantities_so_a_full_line_is_caught():
    _, assign, _, _ = _run(["000918"], [OK], on_order=[])
    assert assign.call_args.kwargs["line_quantities"] == {SKU: 2}


def test_a_full_line_changes_nothing_unless_a_cable_is_picked():
    result, assign, release, label = _run(["000918", "q"], [FULL])
    assert assign.call_count == 1
    release.assert_not_called()
    label.assert_not_called()
    assert "not added" in result.context["scanned_cables"][0]


def test_picking_a_number_swaps_the_cables_and_labels_only_the_new_one():
    result, assign, release, label = _run(["000918", "2"], [FULL, OK])
    assert assign.call_args.args[0] == "000918"
    assert "line_quantities" not in assign.call_args.kwargs
    release.assert_called_once_with("000917", channel="wholesale")
    label.assert_called_once_with("000918", SKU)
    notes = " ".join(result.context["scanned_cables"])
    assert "replaces 000917" in notes and "Remove its old label" in notes
    assert result.action == NavigationAction.REPLACE


def test_scanning_the_old_cable_also_swaps_them():
    _, _, release, _ = _run(["000918", "000916"], [FULL, OK])
    release.assert_called_once_with("000916", channel="wholesale")


def test_a_wrong_pick_asks_again():
    _, _, release, _ = _run(["000918", "000999", "1"], [FULL, OK])
    release.assert_called_once_with("000916", channel="wholesale")


def test_a_website_order_swaps_without_labels():
    result, _, release, label = _run(["000918", "1"], [FULL, OK], wholesale=False)
    release.assert_called_once_with("000916", channel="retail")
    label.assert_not_called()
    assert "Remove its old label" not in " ".join(result.context["scanned_cables"])


def test_the_old_cable_stays_if_the_new_one_cannot_go_on():
    result, _, release, label = _run(
        ["000918", "1"], [FULL, {"error": "database", "message": "down"}])
    release.assert_not_called()
    label.assert_not_called()
    assert "not added" in result.context["scanned_cables"][0]


def test_a_failed_release_is_reported_rather_than_hidden():
    result, *_ = _run(["000918", "1"], [FULL, OK],
                      release={"error": "database", "message": "down"})
    assert "still on this order" in result.context["scanned_cables"][-1]


def test_a_cable_that_fails_its_checks_never_offers_a_swap():
    with patch.object(orders, "ERROR_DISPLAY_SEC", 0):
        _, assign, release, _ = _run(["000918"], [{"error": "not_tested", "message": "no"}])
    assert assign.call_count == 1
    release.assert_not_called()


def test_r_takes_a_cable_off_without_assigning_anything():
    result, assign, release, _ = _run(["r", "1"], [])
    assign.assert_not_called()
    release.assert_called_once_with("000916", channel="wholesale")
    assert result.action == NavigationAction.REPLACE


def test_r_can_be_cancelled():
    _, _, release, _ = _run(["r", "q"], [])
    release.assert_not_called()


def test_r_on_an_empty_order_does_nothing():
    _, _, release, _ = _run(["r"], [], on_order=[])
    release.assert_not_called()


# -- db.assign_cable_to_order's quantity check ---------------------------

def _assign(on_order, **kwargs):
    cur = MagicMock()
    cur.fetchone.side_effect = [
        ("000918", "MB", "SC", 15, "-R", None, None, None, True),
        ("000918", "MB"),
    ]
    cur.fetchall.return_value = on_order
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    with patch.object(db_module, "pg_pool") as pool, \
         patch.object(db_module, "record_cable_event"):
        pool.getconn.return_value = conn
        return db_module.assign_cable_to_order(
            "000918", "cust", "order", [SKU], **kwargs), cur


SAME = ("MB", "SC", 15, "-R")
OTHER = ("MB", "SC", 20, "-R")


def test_db_refuses_a_cable_when_its_sku_is_full():
    result, _ = _assign([SAME, SAME], line_quantities={SKU: 2})
    assert result["error"] == "line_full"
    assert result["sku"] == SKU


def test_db_assigns_when_there_is_room():
    result, _ = _assign([SAME, OTHER], line_quantities={SKU: 2})
    assert result["success"] is True


def test_db_skips_the_check_when_not_asked():
    result, cur = _assign([SAME, SAME])
    assert result["success"] is True
    cur.fetchall.assert_not_called()
