#!/usr/bin/env python3
"""Tests for the `f` list: website orders and wholesale orders, paid or not.

A wholesale order is a Shopify draft until paid, and gets packed either
way, so the list carries open drafts too -- but a completed draft has
already become an Order, and listing both would offer the same boxes twice.

What makes an order wholesale is its buyer (a company), not draft-ness: a
paid wholesale order still needs dealer assignment and registration labels.
Getting this wrong is not cosmetic -- a wholesale cable assigned as retail
gets shopify_gid set, and its end buyer can then never register it.

Run: pytest tests/test_outstanding_orders.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenlight.screens.orders import (
    completed_drafts, fulfillment_context, outstanding_orders,
)

DEALER = {
    "__typename": "PurchasingCompany",
    "company": {"id": "gid://shopify/Company/1", "name": "Mill River Music"},
    "location": {"id": "gid://shopify/CompanyLocation/2", "name": "King St"},
}


def _order(name, created, status="UNFULFILLED", skus=(("SC-20GL-R", 2),),
           buyer=None):
    return {
        "id": f"gid://shopify/Order/{name}",
        "purchasingEntity": buyer,
        "name": name,
        "createdAt": created,
        "displayFulfillmentStatus": status,
        "customer": {"displayName": "Shop"},
        "lineItems": {"edges": [
            {"node": {"title": "Cable", "quantity": q, "sku": sku}}
            for sku, q in skus
        ]},
    }


def _draft(name, created, status="INVOICE_SENT", became=None, lines=None,
           buyer=DEALER):
    return {
        "id": f"gid://shopify/DraftOrder/{name}",
        "purchasingEntity": buyer,
        "name": name,
        "createdAt": created,
        "status": status,
        "order": became,
        "customer": {"displayName": "Retailer"},
        "line_items": lines if lines is not None else
        [{"sku": "SC-20GL-R", "quantity": 4, "title": "Cable"}],
    }


def test_orders_and_open_drafts_merge_newest_first():
    entries = outstanding_orders(
        [_order("#1011", "2026-10-01T00:00:00Z")],
        [_draft("#D14", "2026-10-05T00:00:00Z"),
         _draft("#D13", "2026-09-20T00:00:00Z", status="OPEN")])
    assert [e["name"] for e in entries] == ["#D14", "#1011", "#D13"]
    assert [e["kind"] for e in entries] == ["draft", "order", "draft"]


def test_completed_drafts_are_left_out():
    """#D3 completed into #1011, which is already listed as an Order."""
    entries = outstanding_orders(
        [_order("#1011", "2026-10-01T00:00:00Z")],
        [_draft("#D3", "2026-09-30T00:00:00Z", status="COMPLETED",
                became={"name": "#1011",
                        "displayFulfillmentStatus": "UNFULFILLED"})])
    assert [e["name"] for e in entries] == ["#1011"]


def test_drafts_say_they_are_not_orders_yet():
    (entry,) = outstanding_orders([], [_draft("#D14", "2026-10-05")])
    assert "not an order yet" in entry["status"]


def test_line_items_share_one_shape_and_drop_skuless_lines():
    """Shipping and discount lines have no SKU and nothing scans against them."""
    entries = outstanding_orders(
        [_order("#1011", "2026-10-01", skus=(("SC-20GL-R", 2), (None, 1)))],
        [_draft("#D14", "2026-10-05", lines=[
            {"sku": "SC-10GL-R", "quantity": 3, "title": "Cable"},
            {"sku": "", "quantity": 1, "title": "Shipping"},
        ])])
    by_name = {e["name"]: e["line_items"] for e in entries}
    assert [(li["sku"], li["quantity"]) for li in by_name["#1011"]] == [("SC-20GL-R", 2)]
    assert [(li["sku"], li["quantity"]) for li in by_name["#D14"]] == [("SC-10GL-R", 3)]


def test_nothing_from_shopify_is_an_empty_list():
    assert outstanding_orders([], []) == []
    assert outstanding_orders(None, None) == []


def test_channel_comes_from_the_buyer_not_draft_ness():
    entries = outstanding_orders(
        [_order("#1001", "2026-10-01"),
         _order("#1012", "2026-10-02", buyer=DEALER)],
        [_draft("#D14", "2026-10-05")])
    channels = {e["name"]: e["channel"] for e in entries}
    assert channels == {"#1001": "retail", "#1012": "wholesale",
                        "#D14": "wholesale"}


def test_paid_order_inherits_dealer_from_its_draft():
    """Belt and braces: if the Order comes back without purchasingEntity,
    the completed draft it came from still says who the dealer is."""
    order_gid = "gid://shopify/Order/#1012"
    (entry,) = outstanding_orders(
        [_order("#1012", "2026-10-02")],
        [_draft("#D9", "2026-10-01", status="COMPLETED",
                became={"id": order_gid, "name": "#1012"})])
    assert entry["channel"] == "wholesale"
    assert entry["buyer"]["company_gid"] == "gid://shopify/Company/1"


def test_completed_drafts_map_to_their_orders():
    drafts = [
        _draft("#D3", "2026-09-30", status="COMPLETED",
               became={"id": "gid://shopify/Order/1011", "name": "#1011"}),
        _draft("#D14", "2026-10-05"),
    ]
    assert completed_drafts(drafts) == {
        "gid://shopify/DraftOrder/#D3": "gid://shopify/Order/1011"}


def test_wholesale_context_carries_the_dealer():
    (entry,) = outstanding_orders([], [_draft("#D14", "2026-10-05")])
    ctx = fulfillment_context({"operator": "ADW"}, entry)
    assert ctx["company_gid"] == "gid://shopify/Company/1"
    assert ctx["location_gid"] == "gid://shopify/CompanyLocation/2"
    assert ctx["dealer_name"] == "Mill River Music — King St"
    assert ctx["order_id"] == "gid://shopify/DraftOrder/#D14"
    assert ctx["operator"] == "ADW"


def test_retail_context_has_no_dealer():
    (entry,) = outstanding_orders([_order("#1001", "2026-10-01")], [])
    ctx = fulfillment_context({}, entry)
    assert ctx["company_gid"] is None
    assert ctx["selected_customer"] == {"displayName": "Shop"}
