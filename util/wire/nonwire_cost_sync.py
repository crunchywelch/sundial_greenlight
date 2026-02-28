#!/usr/bin/env python3
"""
Compare and sync non-wire product costs to the Sundial Wire Shopify store.

Reads the consolidated cost data from SQLite (sku_costs table) and compares
against current Shopify variant costs. Reports differences and optionally
updates Shopify to match.

Usage:
    python util/nonwire_cost_sync.py           # Preview differences
    python util/nonwire_cost_sync.py --fix     # Update Shopify to match DB
"""

import sys
import json
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import shopify
from greenlight.shopify_client import get_wire_shopify_session, close_shopify_session
from util.wire.sundial_db import get_db


def load_db_costs(conn):
    """Load non-wire SKU costs from SQLite.

    Returns dict of SKU -> {cost, vendor, notes}.
    """
    rows = conn.execute(
        "SELECT sku, cost, vendor, notes FROM sku_costs"
    ).fetchall()
    return {row["sku"]: {"cost": row["cost"], "vendor": row["vendor"] or "",
                         "notes": row["notes"] or ""} for row in rows}


def fetch_nonwire_variants():
    """Fetch all non-wire variants from the Shopify store with cost data.

    Returns dict mapping SKU -> variant details.
    Excludes W-prefix (wire) SKUs.
    """
    try:
        session = get_wire_shopify_session()

        variants = {}
        has_next_page = True
        cursor = None

        query = """
        query getProducts($limit: Int!, $cursor: String) {
            products(first: $limit, after: $cursor) {
                pageInfo { hasNextPage endCursor }
                edges {
                    node {
                        id
                        variants(first: 100) {
                            edges {
                                node {
                                    id
                                    sku
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
                print(f"   GraphQL errors: {data['errors']}")
                break

            products_data = data.get("data", {}).get("products", {})
            edges = products_data.get("edges", [])
            page_info = products_data.get("pageInfo", {})

            for edge in edges:
                product = edge["node"]
                product_id = product["id"]

                for v_edge in product.get("variants", {}).get("edges", []):
                    v = v_edge["node"]
                    sku = (v.get("sku") or "").strip()
                    if not sku or sku.startswith("W"):
                        continue

                    inv = v.get("inventoryItem") or {}
                    unit_cost = inv.get("unitCost") or {}
                    cost_amt = unit_cost.get("amount")

                    variants[sku] = {
                        "variant_id": v["id"],
                        "product_id": product_id,
                        "cost": float(cost_amt) if cost_amt else None,
                    }

            has_next_page = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")

        return variants

    except Exception as e:
        print(f"   Error fetching store variants: {e}")
        return {}
    finally:
        close_shopify_session()


def compare_costs(db_costs, shopify_variants):
    """Compare DB costs against Shopify and categorize results."""
    db_skus = set(db_costs.keys())
    shopify_skus = set(shopify_variants.keys())

    matches = []
    mismatches = []

    for sku in sorted(db_skus & shopify_skus):
        db_cost = db_costs[sku]["cost"]
        vendor = db_costs[sku]["vendor"]
        notes = db_costs[sku]["notes"]
        shopify_cost = shopify_variants[sku]["cost"]

        if shopify_cost is not None and abs(db_cost - shopify_cost) <= 0.01:
            matches.append(sku)
        else:
            mismatches.append({
                "sku": sku,
                "vendor": vendor,
                "notes": notes,
                "db_cost": db_cost,
                "shopify_cost": shopify_cost,
                "variant_id": shopify_variants[sku]["variant_id"],
                "product_id": shopify_variants[sku]["product_id"],
            })

    return {
        "matches": matches,
        "mismatches": mismatches,
        "db_only": sorted(db_skus - shopify_skus),
        "shopify_only": sorted(shopify_skus - db_skus),
    }


def update_variant_cost(product_id, variant_id, cost):
    """Update a single Shopify variant's cost."""
    try:
        session = get_wire_shopify_session()
        mutation = """
        mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
            productVariantsBulkUpdate(productId: $productId, variants: $variants) {
                productVariants { id }
                userErrors { field message }
            }
        }
        """
        variables = {
            "productId": product_id,
            "variants": [{
                "id": variant_id,
                "inventoryItem": {"cost": cost},
            }],
        }
        result = shopify.GraphQL().execute(mutation, variables=variables)
        data = json.loads(result)

        if "errors" in data:
            return False, str(data["errors"])

        user_errors = (
            data.get("data", {})
            .get("productVariantsBulkUpdate", {})
            .get("userErrors", [])
        )
        if user_errors:
            return False, "; ".join(e["message"] for e in user_errors)

        return True, None
    except Exception as e:
        return False, str(e)
    finally:
        close_shopify_session()


def main():
    parser = argparse.ArgumentParser(
        description="Compare and sync non-wire product costs to Shopify"
    )
    parser.add_argument(
        "--fix", action="store_true", help="Update Shopify costs to match DB"
    )
    args = parser.parse_args()

    print("Non-Wire Product Cost Sync")
    print("=" * 80)
    print()

    # Load DB costs
    conn = get_db()
    print("Loading costs from SQLite...")
    db_costs = load_db_costs(conn)
    conn.close()
    print(f"   {len(db_costs)} SKUs with cost data")
    print()

    # Fetch Shopify data
    print("Fetching non-wire variants from Shopify...")
    shopify_variants = fetch_nonwire_variants()
    print(f"   {len(shopify_variants)} non-wire variants from Shopify")
    print()

    # Compare
    results = compare_costs(db_costs, shopify_variants)

    matches = results["matches"]
    mismatches = results["mismatches"]
    db_only = results["db_only"]
    shopify_only = results["shopify_only"]

    # Detail: mismatches
    def _fmt_cost(val):
        if val is None:
            return "not set"
        return f"${val:.2f}"

    if mismatches:
        print(f"Cost differences ({len(mismatches)}):")
        for m in mismatches:
            print(
                f"   {m['sku']:25}  DB {_fmt_cost(m['db_cost']):>10}"
                f"   Shopify {_fmt_cost(m['shopify_cost']):>10}"
                f"   [{m['vendor']}]"
            )
        print()

    # Detail: DB only
    if db_only:
        print(f"In DB but not in Shopify ({len(db_only)}):")
        for sku in db_only:
            print(f"   {sku}")
        print()

    # Summary
    print("=" * 80)
    print(f"DB SKUs:            {len(db_costs)}")
    print(f"Shopify non-wire:   {len(shopify_variants)}")
    print(f"Cost matches:       {len(matches)}")
    print(f"Cost differences:   {len(mismatches)}")
    print(f"In DB only:         {len(db_only)}")
    print(f"In Shopify only:    {len(shopify_only)}")
    print("=" * 80)
    print()

    if not mismatches:
        print("All matched SKUs have correct costs!")
        return 0

    if not args.fix:
        print(f"Run with --fix to update {len(mismatches)} Shopify variant costs.")
        return 0

    # Apply fixes
    print(f"Updating {len(mismatches)} variant costs in Shopify...")
    print()

    fixed = 0
    failed = 0

    for m in mismatches:
        ok, err = update_variant_cost(m["product_id"], m["variant_id"], m["db_cost"])

        if ok:
            prev = _fmt_cost(m["shopify_cost"])
            print(f"   OK   {m['sku']:25}  {prev:>10} -> ${m['db_cost']:.2f}")
            fixed += 1
        else:
            print(f"   FAIL {m['sku']}: {err}")
            failed += 1

    print()
    print("=" * 80)
    print(f"Done! Updated: {fixed}  Failed: {failed}")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    sys.exit(main())
