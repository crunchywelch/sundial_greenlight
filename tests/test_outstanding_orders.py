#!/usr/bin/env python3
"""Tests for merging unfulfilled Orders and wholesale drafts into the `f` list.

A wholesale order is a Shopify draft until paid. Its boxes get labelled
before then, so the fulfillment list carries drafts too -- but a completed
draft has already become an Order, and listing both would offer the same
boxes twice.

Run: pytest tests/test_outstanding_orders.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenlight.screens.orders import outstanding_orders


def _order(name, created, status="UNFULFILLED", skus=(("SC-20GL-R", 2),)):
    return {
        "id": f"gid://shopify/Order/{name}",
        "name": name,
        "createdAt": created,
        "displayFulfillmentStatus": status,
        "customer": {"displayName": "Shop"},
        "lineItems": {"edges": [
            {"node": {"title": "Cable", "quantity": q, "sku": sku}}
            for sku, q in skus
        ]},
    }


def _draft(name, created, status="INVOICE_SENT", became=None, lines=None):
    return {
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
