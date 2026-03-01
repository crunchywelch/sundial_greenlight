#!/usr/bin/env python3
"""
Zero out inventory for all archived products in the Wire Shopify store.

Fetches archived products, finds any with qty > 0, and sets them to 0.

Usage:
    python util/wire/wire_zero_archived.py         # Preview
    python util/wire/wire_zero_archived.py --fix   # Actually zero them out
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import shopify
from greenlight.shopify_client import get_wire_shopify_session, close_shopify_session
from util.wire.wire_inventory_sync import get_location_id, set_inventory_quantity


def fetch_archived_with_stock():
    """Fetch archived products that still have inventory > 0."""
    try:
        session = get_wire_shopify_session()

        items = []
        has_next_page = True
        cursor = None

        query = """
        query getProducts($limit: Int!, $cursor: String) {
            products(first: $limit, after: $cursor, query: "status:archived") {
                pageInfo { hasNextPage endCursor }
                edges {
                    node {
                        title
                        variants(first: 100) {
                            edges {
                                node {
                                    sku
                                    inventoryQuantity
                                    inventoryItem { id }
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
                print(f"  GraphQL errors: {data['errors']}")
                break

            products_data = data.get("data", {}).get("products", {})
            edges = products_data.get("edges", [])
            page_info = products_data.get("pageInfo", {})

            for edge in edges:
                product = edge["node"]
                for v_edge in product.get("variants", {}).get("edges", []):
                    v = v_edge["node"]
                    sku = (v.get("sku") or "").strip()
                    qty = v.get("inventoryQuantity", 0)
                    if sku and qty > 0:
                        inv = v.get("inventoryItem") or {}
                        items.append({
                            "sku": sku,
                            "title": product.get("title", ""),
                            "qty": qty,
                            "inventory_item_id": inv.get("id"),
                        })

            has_next_page = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")

        return items

    except Exception as e:
        print(f"  Error: {e}")
        return []
    finally:
        close_shopify_session()


def main():
    parser = argparse.ArgumentParser(
        description="Zero out inventory for archived Wire store products"
    )
    parser.add_argument("--fix", action="store_true", help="Actually set quantities to 0")
    args = parser.parse_args()

    print("Finding archived products with stock...")
    items = fetch_archived_with_stock()

    if not items:
        print("No archived products with inventory > 0.")
        return 0

    print(f"\n{len(items)} archived SKUs with stock:\n")
    for item in sorted(items, key=lambda x: x["sku"]):
        print(f"  {item['sku']:25}  qty: {item['qty']:>10}")

    total_qty = sum(i["qty"] for i in items)
    print(f"\n  Total phantom inventory: {total_qty:,}")

    if not args.fix:
        print(f"\nRun with --fix to zero out {len(items)} SKUs in Shopify.")
        return 0

    print("\nFetching location ID...")
    location_id = get_location_id()
    if not location_id:
        print("  ERROR: Could not determine Shopify location")
        return 1

    print(f"Zeroing out {len(items)} SKUs...\n")
    fixed = 0
    failed = 0

    for item in sorted(items, key=lambda x: x["sku"]):
        ok, err = set_inventory_quantity(item["inventory_item_id"], location_id, 0)
        if ok:
            print(f"  OK   {item['sku']:25}  {item['qty']} -> 0")
            fixed += 1
        else:
            print(f"  FAIL {item['sku']}: {err}")
            failed += 1

    print(f"\nDone! Zeroed: {fixed}  Failed: {failed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
