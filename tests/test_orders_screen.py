#!/usr/bin/env python3
"""Tests for the `o` screen: open orders, completed orders, and what each allows.

The rule that matters most: a completed order is view-only. Scanning a cable
there can reprint its label, but must never assign it to the order.

Run: pytest tests/test_orders_screen.py  (no DB, no Shopify, no printer)
"""

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from rich.console import Console

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenlight.screen_manager import NavigationAction
from greenlight.screens import orders
from greenlight.screens.orders import (
    CompletedOrderScreen, OrderFulfillScanScreen, OrdersScreen, cables_cell,
    completed_orders, other_cables,
)

LINES = [{"sku": "SC-20GL-R", "quantity": 2, "title": "Cable"}]
GID = "gid://shopify/Order/1"


def _order(name="#1", status="FULFILLED"):
    return {
        "id": f"gid://shopify/Order/{name.lstrip('#')}",
        "name": name,
        "createdAt": "2026-10-01",
        "displayFulfillmentStatus": status,
        "customer": {"displayName": "Buyer"},
        "lineItems": {"edges": [
            {"node": {"title": "Cable", "quantity": 2, "sku": "SC-20GL-R"}}]},
    }


def _cable(serial, sku="SC-20GL-R"):
    return {"serial_number": serial, "variant_sku": sku}


def _cancelled(name="#2"):
    return {**_order(name, status="UNFULFILLED"), "cancelledAt": "2026-07-30T15:49:13Z"}


def _ui(*typed, page_size=20):
    ui = MagicMock()
    ui.page_size.return_value = page_size
    ui.console.input.side_effect = list(typed)
    return ui


def _orders_screen(ui, fulfilled=(), unfulfilled=()):
    client = patch.multiple(
        orders.shopify_client,
        get_completed_orders=MagicMock(return_value=list(fulfilled)),
        get_unfulfilled_orders=MagicMock(return_value=list(unfulfilled)),
        get_draft_orders=MagicMock(return_value=[]))
    database = patch.multiple(
        orders.db,
        relink_order_cables=MagicMock(return_value=0),
        get_cables_for_orders=MagicMock(return_value={}))
    return OrdersScreen(ui, {"operator": "AW"}), client, database


def _completed_screen(typed, wholesale=True, cables=(_cable("000001"),)):
    ui = MagicMock()
    ui.get_serial_number_scan_or_manual.side_effect = list(typed)
    context = {
        "order_id": GID, "order_name": "#1", "line_items": LINES,
        "company_gid": "gid://shopify/Company/1" if wholesale else None,
        "dealer_name": "Mill River Music" if wholesale else None,
        "selected_customer": {"displayName": "Buyer"},
    }
    return CompletedOrderScreen(ui, context), {GID: list(cables)}


# -- the Cables column ---------------------------------------------------

def test_cables_cell_counts_scanned_of_needed():
    assert cables_cell(LINES, []) == "0/2"
    assert cables_cell(LINES, [_cable("000001")]) == "[yellow]1/2[/yellow]"
    assert cables_cell(LINES, [_cable("000001"), _cable("000002")]) == "[green]2/2[/green]"


def test_cables_cell_ignores_cables_of_another_sku():
    assert cables_cell(LINES, [_cable("000001", "OTHER")]) == "0/2"


def test_unreadable_database_is_not_reported_as_no_cables():
    assert cables_cell(LINES, None) == "[dim]?/2[/dim]"


def test_a_closed_order_with_no_record_is_not_flagged_as_work():
    assert cables_cell(LINES, [], closed=True) == "[dim]0/2[/dim]"
    assert cables_cell(LINES, [_cable("000001")], closed=True) == "[dim]1/2[/dim]"


def test_a_closed_order_counts_cables_shipped_under_another_sku():
    """#1012: one-offs listed as TC-MISC-51 shipped as TC-6-LTD-LISTONS2026."""
    cables = [_cable("000001", "OTHER"), _cable("000002", "OTHER")]
    assert cables_cell(LINES, cables, closed=True) == "[green]2/2[/green]"
    assert cables_cell(LINES, cables) == "0/2"      # an open order still needs them


def test_other_cables_are_those_on_no_line():
    cables = [_cable("000001"), _cable("000002", "OTHER")]
    assert [c["serial_number"] for c in other_cables(LINES, cables)] == ["000002"]


def _rendered(renderable):
    console = Console(width=120, record=True, file=io.StringIO())
    console.print(renderable)
    return console.export_text()


def test_completed_order_lists_cables_with_no_matching_line():
    text = _rendered(CompletedOrderScreen._body(
        "#1", "who", LINES, [_cable("000002", "OTHER")], ""))
    assert "Other cables on this order" in text
    assert "000002  OTHER" in text
    assert "no SKU match" in text
    assert "No cables were scanned" not in text


def test_completed_order_with_no_cables_says_so():
    text = _rendered(CompletedOrderScreen._body("#1", "who", LINES, [], ""))
    assert "No cables were scanned" in text
    assert "2 not scanned" in text
    assert "Other cables" not in text


def test_a_cable_with_another_sku_can_still_reprint():
    screen, found = _completed_screen(["000002", "q"],
                                      cables=(_cable("000002", "OTHER"),))
    _, assign, _, _, send = _run_completed(screen, found)
    send.assert_called_once_with("000002", "ABC123", "OTHER")
    assign.assert_not_called()


# -- which orders are completed ------------------------------------------

def test_open_drafts_are_never_completed_orders():
    draft = {"id": "gid://shopify/DraftOrder/9", "name": "#D9",
             "status": "INVOICE_SENT", "createdAt": "2026-10-02", "order": None,
             "customer": {}, "line_items": LINES}
    assert [e["name"] for e in completed_orders([_order()], [draft])] == ["#1"]


def test_completed_order_from_a_draft_keeps_its_wholesale_buyer():
    draft = {"id": "gid://shopify/DraftOrder/9", "name": "#D9",
             "status": "COMPLETED", "createdAt": "2026-10-02",
             "order": {"id": "gid://shopify/Order/1"},
             "customer": {}, "line_items": LINES,
             "purchasingEntity": {
                 "__typename": "PurchasingCompany",
                 "company": {"id": "gid://shopify/Company/1", "name": "Mill River"},
                 "location": {"id": "gid://shopify/CompanyLocation/2", "name": "King St"}}}
    entry = completed_orders([_order()], [draft])[0]
    assert entry["channel"] == "wholesale"


def test_a_cancelled_order_says_so_instead_of_unfulfilled():
    entry = completed_orders([_cancelled()], [])[0]
    assert entry["status"] == "Cancelled"
    assert entry["cancelled"] is True


def test_a_fulfilled_order_is_not_cancelled():
    entry = completed_orders([_order()], [])[0]
    assert entry["status"] == "Fulfilled"
    assert entry["cancelled"] is False


def _with_search_results(nodes, call):
    with patch.object(orders.shopify_client, "_search_orders", return_value=nodes):
        return [o["name"] for o in call()]


def test_cancelled_orders_are_off_the_open_list():
    nodes = [_cancelled("#2"), _order("#3", status="UNFULFILLED")]
    assert _with_search_results(nodes, orders.shopify_client.get_unfulfilled_orders) == ["#3"]


def test_cancelled_orders_are_on_the_completed_list():
    nodes = [_cancelled("#2"), _order("#3"), _order("#4", status="UNFULFILLED")]
    assert _with_search_results(nodes, orders.shopify_client.get_completed_orders) == ["#2", "#3"]


def test_a_cancelled_order_opens_view_only():
    ui = _ui("c", "1")
    screen, client, database = _orders_screen(ui, fulfilled=[_cancelled()])
    with client, database:
        result = screen.run()
    assert result.screen_class is CompletedOrderScreen
    assert result.context["cancelled"] is True


def test_a_cancelled_order_says_cancelled_rather_than_shipped_unscanned():
    text = _rendered(CompletedOrderScreen._body("#2", "who", LINES, [], "", cancelled=True))
    assert "This order was cancelled" in text
    assert "shipped without scanning" not in text


# -- navigating the list -------------------------------------------------

def _body_title(ui):
    return ui.layout["body"].update.call_args.args[0].title


def test_opens_on_open_orders_and_c_switches_to_completed():
    ui = _ui("c", "q", "q")
    screen, client, database = _orders_screen(ui, fulfilled=[_order()])
    with client, database:
        result = screen.run()
    assert result.action == NavigationAction.POP
    assert screen.view == "open"


def test_q_from_completed_returns_to_open_not_the_hub():
    ui = _ui("c", "q", KeyboardInterrupt())
    screen, client, database = _orders_screen(ui, fulfilled=[_order()])
    with client, database:
        screen.run()
    assert screen.view == "open"
    assert ui.console.input.call_count == 3


def test_a_completed_order_opens_view_only():
    ui = _ui("c", "1")
    screen, client, database = _orders_screen(ui, fulfilled=[_order()])
    with client, database:
        result = screen.run()
    assert result.screen_class is CompletedOrderScreen


def test_an_open_order_opens_for_scanning_and_returns_to_the_list():
    ui = _ui("1")
    screen, client, database = _orders_screen(
        ui, unfulfilled=[_order(status="UNFULFILLED")])
    with client, database:
        result = screen.run()
    assert result.screen_class is OrderFulfillScanScreen
    assert result.context["assign_return_to"] is OrdersScreen


def test_the_list_stays_on_completed_after_coming_back_from_an_order():
    ui = _ui("c", "1", "1")
    screen, client, database = _orders_screen(ui, fulfilled=[_order()])
    with client, database:
        screen.run()
        assert screen.run().screen_class is CompletedOrderScreen


def test_row_numbers_carry_across_pages():
    many = [_order(f"#{i}", status="UNFULFILLED") for i in range(1, 8)]
    ui = _ui("n", "4", page_size=3)
    screen, client, database = _orders_screen(ui, unfulfilled=many)
    with client, database:
        result = screen.run()
    assert screen.page == 1
    assert result.context["order_name"] == "#4"


def test_shopify_failure_on_completed_is_not_reported_as_no_orders():
    ui = _ui("c", "q", "q")
    screen, client, database = _orders_screen(ui)
    with client, database:
        orders.shopify_client.get_completed_orders.side_effect = RuntimeError("down")
        titles = []
        ui.layout["body"].update.side_effect = (
            lambda panel: titles.append(str(panel.renderable)))
        screen.run()
    assert any("Can't reach Shopify" in t for t in titles)


# -- completed orders are view-only --------------------------------------

def _run_completed(screen, found, code="ABC123"):
    """Runs the screen; returns its result and the mocks that must stay quiet."""
    with patch.object(orders.db, "get_cables_for_orders", return_value=found), \
         patch.object(orders.db, "get_audio_cable",
                      return_value={"registration_code": code}), \
         patch.object(orders.db, "assign_cable_to_order") as assign, \
         patch.object(orders.db, "force_assign_cable_to_order") as force, \
         patch("greenlight.screens.registration_codes.ensure_registration_code") as ensure, \
         patch.object(orders, "send_registration_label",
                      return_value=" printed") as send:
        result = screen.run()
    return result, assign, force, ensure, send


def test_scanning_a_cable_on_the_order_reprints_its_label_and_assigns_nothing():
    screen, found = _completed_screen(["000001", "q"])
    result, assign, force, ensure, send = _run_completed(screen, found)
    send.assert_called_once_with("000001", "ABC123", "SC-20GL-R")
    assign.assert_not_called()
    force.assert_not_called()
    assert result.action == NavigationAction.POP


def test_scanning_a_cable_not_on_the_order_does_nothing():
    screen, found = _completed_screen(["000999", "q"])
    _, assign, force, ensure, send = _run_completed(screen, found)
    send.assert_not_called()
    assign.assert_not_called()
    force.assert_not_called()
    ensure.assert_not_called()


def test_a_cable_with_no_code_does_not_get_one_here():
    screen, found = _completed_screen(["000001", "q"])
    _, _, _, ensure, send = _run_completed(screen, found, code=None)
    ensure.assert_not_called()
    send.assert_not_called()


def test_a_website_order_has_nothing_to_scan():
    screen, found = _completed_screen([], wholesale=False)
    result, assign, _, _, send = _run_completed(screen, found)
    screen.ui.get_serial_number_scan_or_manual.assert_not_called()
    screen.ui.wait_back.assert_called_once()
    assign.assert_not_called()
    send.assert_not_called()
    assert result.action == NavigationAction.POP


def test_box_labels_are_reachable_from_a_completed_wholesale_order():
    from greenlight.screens.order_labels import OrderLabelPrintScreen
    screen, found = _completed_screen(["l"])
    result, *_ = _run_completed(screen, found)
    assert result.screen_class is OrderLabelPrintScreen
    assert result.context["label_order"]["line_items"] == LINES
    assert result.context["label_order"]["customer"]["displayName"] == "Mill River Music"
