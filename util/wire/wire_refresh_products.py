#!/usr/bin/env python3
"""
Refresh product quantities and costs from the Shopify Wire store into SQLite.

Fetches all products via GraphQL and updates the products table and
inventory_snapshots with current data from Shopify.

Usage:
    python util/refresh_products.py           # Refresh all products
    python util/refresh_products.py --sku W143CPDBXXS  # Check a specific SKU
"""

import sys
import json
import argparse
from datetime import date
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import shopify
from greenlight.shopify_client import get_wire_shopify_session, close_shopify_session
from util.wire.sundial_wire_db import get_db, init_db, upsert_products, upsert_inventory_snapshot


def fetch_all_products():
    """Fetch all products from Wire Shopify store with qty and cost.

    Returns list of dicts ready for upsert_products.
    """
    try:
        session = get_wire_shopify_session()

        items = []
        has_next_page = True
        cursor = None

        query = """
        query getProducts($limit: Int!, $cursor: String) {
            products(first: $limit, after: $cursor, query: "status:active") {
                pageInfo { hasNextPage endCursor }
                edges {
                    node {
                        handle
                        title
                        productType
                        variants(first: 100) {
                            edges {
                                node {
                                    sku
                                    price
                                    selectedOptions { name value }
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
                print(f"  GraphQL errors: {data['errors']}")
                break

            products_data = data.get("data", {}).get("products", {})
            edges = products_data.get("edges", [])
            page_info = products_data.get("pageInfo", {})

            for edge in edges:
                product = edge["node"]
                handle = product.get("handle", "")
                title = product.get("title", "")
                product_type = product.get("productType", "")

                for v_edge in product.get("variants", {}).get("edges", []):
                    v = v_edge["node"]
                    sku = (v.get("sku") or "").strip()
                    if not sku:
                        continue

                    price = float(v["price"]) if v.get("price") else None
                    qty = v.get("inventoryQuantity", 0)
                    inv = v.get("inventoryItem") or {}
                    unit_cost = inv.get("unitCost") or {}
                    cost = float(unit_cost["amount"]) if unit_cost.get("amount") else None

                    # Extract first option value
                    options = v.get("selectedOptions", [])
                    option = options[0]["value"] if options else ""

                    items.append({
                        "sku": sku,
                        "handle": handle,
                        "title": title,
                        "option": option,
                        "product_type": product_type,
                        "qty": qty,
                        "price": price,
                        "is_wire": 1 if sku.startswith("W") else 0,
                        "cost": cost,
                    })

            has_next_page = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")

        return items

    except Exception as e:
        print(f"  Error fetching products: {e}")
        raise
    finally:
        close_shopify_session()


def refresh_from_shopify(conn):
    """Fetch latest product data from Shopify and update SQLite.

    Returns (product_count, snapshot_count).
    """
    items = fetch_all_products()
    print(f"  Fetched {len(items)} variants from Shopify")

    init_db(conn)
    today = date.today().isoformat()

    upsert_products(conn, items)

    snapshot_count = 0
    for item in items:
        if item["cost"] is not None:
            upsert_inventory_snapshot(
                conn, item["sku"], today, item["qty"], item["cost"], "shopify_live"
            )
            snapshot_count += 1

    print(f"  Updated {len(items)} products")
    print(f"  Updated {snapshot_count} inventory snapshots (date: {today})")
    print()

    return len(items), snapshot_count


def main():
    parser = argparse.ArgumentParser(
        description="Refresh product data from Shopify Wire store into SQLite"
    )
    parser.add_argument("--sku", help="Show data for a specific SKU after refresh")
    args = parser.parse_args()

    print("Refreshing products from Shopify Wire store...")
    print()

    conn = get_db()
    refresh_from_shopify(conn)

    # Summary
    wire = conn.execute("SELECT COUNT(*) FROM products WHERE is_wire = 1").fetchone()[0]
    nonwire = conn.execute("SELECT COUNT(*) FROM products WHERE is_wire = 0").fetchone()[0]
    print(f"  Wire products:     {wire}")
    print(f"  Non-wire products: {nonwire}")
    print(f"  Total:             {wire + nonwire}")

    # Show specific SKU if requested
    if args.sku:
        print()
        print(f"Data for {args.sku}:")
        row = conn.execute(
            "SELECT * FROM products WHERE sku = ?", (args.sku,)
        ).fetchone()
        if row:
            for key in row.keys():
                print(f"  {key}: {row[key]}")
        else:
            print(f"  SKU not found")

        snap = conn.execute(
            "SELECT * FROM inventory_snapshots WHERE sku = ? ORDER BY snapshot_date DESC",
            (args.sku,)
        ).fetchall()
        if snap:
            print(f"  Snapshots:")
            for s in snap:
                print(f"    {s['snapshot_date']}: qty={s['qty']}, cost={s['cost']}, source={s['source']}")

    conn.close()
    print()
    print("Done!")


if __name__ == "__main__":
    sys.exit(main() or 0)
