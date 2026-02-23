#!/usr/bin/env python3
"""
Report total cost of available inventory in Shopify for bookkeeping.

Fetches all product variants from Shopify with their inventory quantities
and unit costs, then calculates total inventory value.

Usage:
    python util/inventory_value.py            # Summary by series
    python util/inventory_value.py --detail   # Show every SKU
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import shopify
from greenlight.shopify_client import get_shopify_session, close_shopify_session


def fetch_inventory():
    """Fetch all Shopify variants with inventory quantity and cost.

    Returns list of dicts with sku, quantity, cost, product_title.
    """
    try:
        session = get_shopify_session()

        items = []
        has_next_page = True
        cursor = None

        query = """
        query getProducts($limit: Int!, $cursor: String) {
            products(first: $limit, after: $cursor) {
                pageInfo { hasNextPage endCursor }
                edges {
                    node {
                        title
                        productType
                        status
                        variants(first: 100) {
                            edges {
                                node {
                                    sku
                                    inventoryQuantity
                                    inventoryItem {
                                        unitCost {
                                            amount
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """

        while has_next_page:
            variables = {"limit": 250, "cursor": cursor}
            result = shopify.GraphQL().execute(query, variables=variables)
            data = json.loads(result)

            if "errors" in data:
                print(f"GraphQL errors: {data['errors']}")
                break

            products_data = data.get("data", {}).get("products", {})
            edges = products_data.get("edges", [])
            page_info = products_data.get("pageInfo", {})

            for edge in edges:
                product = edge["node"]
                if product.get("status") != "ACTIVE":
                    continue

                for v_edge in product.get("variants", {}).get("edges", []):
                    v = v_edge["node"]
                    sku = (v.get("sku") or "").strip()
                    if not sku:
                        continue

                    qty = v.get("inventoryQuantity", 0)
                    inv = v.get("inventoryItem") or {}
                    unit_cost = inv.get("unitCost") or {}
                    cost = float(unit_cost["amount"]) if unit_cost.get("amount") else None

                    items.append({
                        "sku": sku,
                        "product_title": product["title"],
                        "product_type": product.get("productType", ""),
                        "quantity": qty,
                        "unit_cost": cost,
                    })

            has_next_page = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")

        return items

    except Exception as e:
        print(f"Error fetching inventory: {e}")
        return []
    finally:
        close_shopify_session()


def _series_from_sku(sku):
    """Derive series name from SKU prefix."""
    prefixes = {
        "SC-": "Studio Classic",
        "SV-": "Studio Vocal",
        "TC-": "Tour Classic",
        "TV-": "Tour Vocal",
    }
    for prefix, name in prefixes.items():
        if sku.startswith(prefix):
            return name
    return "Other"


def main():
    parser = argparse.ArgumentParser(
        description='Report total cost of available Shopify inventory'
    )
    parser.add_argument('--detail', action='store_true',
                        help='Show per-SKU breakdown')
    args = parser.parse_args()

    print("Fetching Shopify inventory...")
    items = fetch_inventory()

    if not items:
        print("No inventory found.")
        return 1

    # Filter to items with stock and cost
    stocked = [i for i in items if i["quantity"] > 0]
    no_cost = [i for i in stocked if i["unit_cost"] is None]

    # Group by series
    by_series = {}
    for item in stocked:
        series = _series_from_sku(item["sku"])
        if series not in by_series:
            by_series[series] = []
        by_series[series].append(item)

    # Detail view
    if args.detail:
        print()
        for series in sorted(by_series.keys()):
            print(f"{series}")
            print(f"{'─' * 60}")
            series_total = 0
            for item in sorted(by_series[series], key=lambda x: x["sku"]):
                qty = item["quantity"]
                cost = item["unit_cost"]
                if cost is not None:
                    ext = qty * cost
                    series_total += ext
                    print(f"  {item['sku']:22} {qty:>4} x ${cost:>7.2f} = ${ext:>9.2f}")
                else:
                    print(f"  {item['sku']:22} {qty:>4} x   no cost")
            print(f"  {'':22} {'':>4}   {'':>7}   ${series_total:>9.2f}")
            print()

    # Summary
    print()
    print("Inventory Value Summary")
    print("=" * 50)

    grand_total = 0
    grand_units = 0

    for series in sorted(by_series.keys()):
        series_items = by_series[series]
        units = sum(i["quantity"] for i in series_items)
        value = sum(i["quantity"] * i["unit_cost"]
                    for i in series_items if i["unit_cost"] is not None)
        grand_total += value
        grand_units += units
        print(f"  {series:22} {units:>4} units   ${value:>10.2f}")

    print(f"  {'─' * 47}")
    print(f"  {'Total':22} {grand_units:>4} units   ${grand_total:>10.2f}")
    print()

    if no_cost:
        print(f"  Warning: {len(no_cost)} SKU(s) with stock but no cost set:")
        for item in sorted(no_cost, key=lambda x: x["sku"]):
            print(f"    {item['sku']} ({item['quantity']} units)")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
