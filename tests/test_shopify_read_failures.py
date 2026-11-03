#!/usr/bin/env python3
"""A failed Shopify read must never look like an empty answer.

"Nothing open" sends an operator home, "no such product" creates one, and an
empty catalog makes inventory reconciliation think everything is missing. So
these reads raise, and whoever calls them says Shopify couldn't be reached.

Run: pytest tests/test_shopify_read_failures.py  (no DB, no Shopify, no printer)
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenlight import shopify_client
from greenlight.screen_manager import NavigationAction
from greenlight.screens import orders
from greenlight.screens.order_labels import OrderLabelPrintScreen
from greenlight.screens.orders import (
    CustomerDetailScreen, CustomerLookupScreen, CustomerOrdersScreen,
    OrderSelectionScreen, OrdersScreen,
)

ERRORS = {"errors": [{"message": "Throttled"}]}
CUSTOMER = {"id": "gid://shopify/Customer/1", "displayName": "Ann"}
LINE = {"sku": "SC-20GL", "quantity": 1, "title": "Cable"}


def _shopify_replies(*replies):
    """Patch the Shopify session and have GraphQL give these replies in turn.

    A reply that's an exception is raised, as a network failure would be.
    """
    graphql = MagicMock()
    graphql.return_value.execute.side_effect = [
        r if isinstance(r, Exception) else json.dumps(r) for r in replies]
    return patch.multiple(shopify_client,
                          get_shopify_session=MagicMock(),
                          close_shopify_session=MagicMock(),
                          shopify=MagicMock(GraphQL=graphql))


READS = [
    lambda: shopify_client.search_customers_by_name("ann"),
    lambda: shopify_client.get_customer_orders("1"),
    lambda: shopify_client.get_unfulfilled_orders(),
    lambda: shopify_client.get_completed_orders(),
    lambda: shopify_client.get_draft_orders(),
    lambda: shopify_client.get_draft_order_by_name("D1"),
    lambda: shopify_client.get_all_products(),
    lambda: shopify_client.get_all_product_skus(),
    lambda: shopify_client._find_variant_by_sku("SC-20GL"),
]


@pytest.mark.parametrize("read", READS)
def test_graphql_errors_raise(read):
    with _shopify_replies(ERRORS), pytest.raises(RuntimeError):
        read()


@pytest.mark.parametrize("read", READS)
def test_network_failure_raises(read):
    with _shopify_replies(ConnectionError("down")), pytest.raises(ConnectionError):
        read()


def test_a_customer_shopify_no_longer_has_just_has_no_orders():
    with _shopify_replies({"data": {"customer": None}}):
        assert shopify_client.get_customer_orders("1") == []


def _products_page(has_next):
    return {"data": {"products": {
        "edges": [{"node": {"id": "p1", "title": "Cable"}}],
        "pageInfo": {"hasNextPage": has_next, "endCursor": "c"}}}}


@pytest.mark.parametrize("failure", [ERRORS, ConnectionError("down")])
def test_part_of_a_catalog_never_passes_for_all_of_it(failure):
    with _shopify_replies(_products_page(True), failure), pytest.raises(Exception):
        shopify_client.get_all_products()


def test_a_whole_catalog_still_comes_back():
    with _shopify_replies(_products_page(True), _products_page(False)):
        assert len(shopify_client.get_all_products()) == 2


# -- nothing gets written on the strength of a failed read -----------------

def test_a_failed_lookup_does_not_create_a_product():
    record = {"description": "One off", "variant_sku": "SC-MISC-1"}
    with _shopify_replies(ERRORS), \
            patch.object(shopify_client, "_create_special_baby_product") as create:
        ok, error = shopify_client.ensure_misc_shopify_product(record)
    assert not ok and "SC-MISC-1" in error
    create.assert_not_called()


def test_a_missing_product_still_gets_created():
    record = {"description": "One off", "variant_sku": "SC-MISC-1"}
    empty = {"data": {"productVariants": {"edges": []}}}
    with _shopify_replies(empty), \
            patch.object(shopify_client, "_create_special_baby_product",
                         return_value=(True, None)) as create:
        assert shopify_client.ensure_misc_shopify_product(record) == (True, None)
    create.assert_called_once()


def test_inventory_fix_stops_before_writing_if_shopify_is_down():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "audio"))
    import audio_shopify_inventory_reconcile as reconcile
    with patch.object(reconcile, "get_postgres_available_counts",
                      return_value={"SC-20GL": 3, "SC-MISC-1": 1}), \
            patch.object(reconcile, "get_all_product_skus",
                         side_effect=RuntimeError("down")), \
            patch.object(reconcile, "set_inventory_for_sku") as set_inventory, \
            patch.object(reconcile, "ensure_misc_shopify_product") as ensure:
        with pytest.raises(RuntimeError):
            reconcile.fix_mismatches()
    set_inventory.assert_not_called()
    ensure.assert_not_called()


# -- screens say so --------------------------------------------------------

def _ui(*typed):
    ui = MagicMock()
    ui.page_size.return_value = 20
    ui.console.input.side_effect = list(typed)
    ui.shown = []
    for part in ("body", "footer"):
        ui.layout[part].update.side_effect = (
            lambda panel: ui.shown.append(str(panel.renderable)))
    return ui


def _shown(ui, text):
    return any(text in s for s in ui.shown)


@pytest.mark.parametrize("failing", ["get_unfulfilled_orders", "get_draft_orders"])
def test_open_list_does_not_say_nothing_open(failing):
    ui = _ui("q")
    with patch.multiple(orders.shopify_client,
                        get_unfulfilled_orders=MagicMock(return_value=[]),
                        get_draft_orders=MagicMock(return_value=[])), \
            patch.multiple(orders.db,
                           relink_order_cables=MagicMock(return_value=0),
                           get_cables_for_orders=MagicMock(return_value={})):
        getattr(orders.shopify_client, failing).side_effect = RuntimeError("down")
        OrdersScreen(ui, {"operator": "AW"}).run()
    assert _shown(ui, "Can't reach Shopify")
    assert not _shown(ui, "Nothing open")


def test_customer_search_does_not_say_nobody_matched():
    ui = _ui("ann")
    with patch.object(orders.shopify_client, "search_customers_by_name",
                      side_effect=RuntimeError("down")):
        result = CustomerLookupScreen(ui, {"operator": "AW"}).run()
    assert _shown(ui, "Can't reach Shopify")
    assert not _shown(ui, "No customers found")
    assert result.screen_class is CustomerLookupScreen


@pytest.mark.parametrize("screen, empty", [
    (CustomerOrdersScreen, "No orders found"),
    (OrderSelectionScreen, "No unfulfilled orders"),
])
def test_customer_orders_do_not_say_there_are_none(screen, empty):
    ui = _ui()
    with patch.object(orders.shopify_client, "get_customer_orders",
                      side_effect=RuntimeError("down")):
        result = screen(ui, {"operator": "AW", "selected_customer": CUSTOMER}).run()
    assert _shown(ui, "Can't reach Shopify")
    assert not _shown(ui, empty)
    assert result.action is NavigationAction.POP


def _customer_detail(ui, get_customer_orders):
    return patch.object(orders.shopify_client, "get_customer_orders",
                        get_customer_orders), \
        patch.object(orders.db, "get_cables_for_customer", return_value=[])


def test_direct_assign_does_not_skip_the_open_order_check():
    # The last-order read works and the open-order check behind `a` doesn't.
    ui = _ui("a")
    reads = MagicMock(side_effect=[[], RuntimeError("down")])
    client, database = _customer_detail(ui, reads)
    with client, database:
        result = CustomerDetailScreen(
            ui, {"operator": "AW", "selected_customer": CUSTOMER}).run()
    assert _shown(ui, "Can't reach Shopify")
    assert result.screen_class is CustomerDetailScreen


def test_customer_detail_still_opens_and_says_the_last_order_is_missing():
    ui = _ui("")
    client, database = _customer_detail(ui, MagicMock(side_effect=RuntimeError("down")))
    with client, database:
        result = CustomerDetailScreen(
            ui, {"operator": "AW", "selected_customer": CUSTOMER}).run()
    assert _shown(ui, "last order not loaded")
    assert result.action is NavigationAction.POP


# -- box labels ------------------------------------------------------------

def _label_screen(*typed):
    ui = _ui(*typed)
    context = {"operator": "AW",
               "label_order": {"name": "#D1", "line_items": [LINE]}}
    return ui, OrderLabelPrintScreen(ui, context)


def _footers(ui):
    return [str(c.args[0].renderable)
            for c in ui.layout["footer"].update.call_args_list]


def test_labels_turn_upc_off_rather_than_blaming_each_sku():
    ui, screen = _label_screen("q")
    with patch.object(shopify_client, "get_all_product_skus",
                      side_effect=RuntimeError("down")) as skus:
        screen.run()
    skus.assert_called_once()
    assert _shown(ui, "UPC label is off")
    assert not _shown(ui, "no UPC in Shopify")


def test_turning_upc_back_on_tries_shopify_again():
    ui, screen = _label_screen("1", "q")
    good = {"SC-20GL": {"barcode": "036000291452"}}
    with patch.object(shopify_client, "get_all_product_skus",
                      side_effect=[RuntimeError("down"), good]) as skus:
        screen.run()
    assert skus.call_count == 2
    assert "UPC label is off" not in _footers(ui)[-1]


# -- customer detail ---------------------------------------------------------

@pytest.mark.parametrize("key", ["q", ""])
def test_customer_detail_goes_back_on_q_or_enter(key):
    ui = _ui(key)
    client, database = _customer_detail(ui, MagicMock(return_value=[]))
    with client, database:
        result = CustomerDetailScreen(
            ui, {"operator": "AW", "selected_customer": CUSTOMER}).run()
    assert result.action is NavigationAction.POP
