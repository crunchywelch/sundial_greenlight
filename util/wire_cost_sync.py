#!/usr/bin/env python3
"""
Compare and sync product costs from inventory CSV to the Wire Shopify store.

Reads the corrected inventory worksheet CSV (source of truth for costs) and
compares against Shopify variant costs. Reports differences and optionally
updates Shopify to match.

Usage:
    python util/wire_cost_sync.py           # Preview differences
    python util/wire_cost_sync.py --fix     # Update Shopify to match CSV
"""

import sys
import csv
import json
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import shopify
from greenlight.shopify_client import get_wire_shopify_session, close_shopify_session

CSV_PATH = Path(__file__).parent.parent / "docs" / "wire_inventory_worksheet_2-4-2026.csv"


def load_csv_costs(csv_path):
    """Parse the inventory CSV into a dict of SKU -> cost.

    Skips the grand-total row (line 1) and any rows without a SKU or cost.
    """
    sku_costs = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        lines = f.readlines()

    # First line is a grand-total row, skip it; line 2 is the header
    reader = csv.DictReader(lines[1:])
    for row in reader:
        sku = (row.get("Variant SKU") or "").strip()
        cost_str = (row.get("Cost per item") or "").strip()
        if not sku or not cost_str:
            continue
        try:
            option = (row.get("Option1 Value") or "").strip()
            sku_costs[sku] = {"cost": float(cost_str), "option": option}
        except ValueError:
            continue

    # Only include wire SKUs (W prefix)
    return {k: v for k, v in sku_costs.items() if k.startswith("W")}


def fetch_wire_variants():
    """Fetch all variants from the Wire Shopify store with cost data.

    Returns dict mapping SKU -> variant details.
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
                    if not sku or not sku.startswith("W"):
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
        print(f"   Error fetching wire store variants: {e}")
        return {}
    finally:
        close_shopify_session()


def compare_costs(csv_costs, shopify_variants):
    """Compare CSV costs against Shopify and categorize results.

    Returns dict with keys: matches, mismatches, csv_only, shopify_only.
    """
    csv_skus = set(csv_costs.keys())
    shopify_skus = set(shopify_variants.keys())

    matches = []
    mismatches = []

    for sku in sorted(csv_skus & shopify_skus):
        csv_cost = csv_costs[sku]["cost"]
        csv_option = csv_costs[sku]["option"]
        shopify_cost = shopify_variants[sku]["cost"]

        if shopify_cost is not None and abs(csv_cost - shopify_cost) <= 0.01:
            matches.append(sku)
        else:
            mismatches.append({
                "sku": sku,
                "option": csv_option,
                "csv_cost": csv_cost,
                "shopify_cost": shopify_cost,
                "variant_id": shopify_variants[sku]["variant_id"],
                "product_id": shopify_variants[sku]["product_id"],
            })

    return {
        "matches": matches,
        "mismatches": mismatches,
        "csv_only": sorted(csv_skus - shopify_skus),
        "shopify_only": sorted(shopify_skus - csv_skus),
    }


def update_variant_cost(product_id, variant_id, cost):
    """Update a single Shopify variant's cost.

    Uses productVariantsBulkUpdate with inventoryItem.cost.
    """
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
        description="Compare and sync Wire store costs from inventory CSV to Shopify"
    )
    parser.add_argument(
        "--fix", action="store_true", help="Update Shopify costs to match CSV"
    )
    args = parser.parse_args()

    print("Wire Store Cost Sync")
    print("=" * 70)
    print()

    # Load CSV costs
    print(f"Loading CSV costs from {CSV_PATH.name}...")
    csv_costs = load_csv_costs(CSV_PATH)
    print(f"   {len(csv_costs)} SKUs with cost data")
    print()

    # Fetch Shopify data
    print("Fetching Wire store variants...")
    shopify_variants = fetch_wire_variants()
    print(f"   {len(shopify_variants)} variants from Shopify")
    print()

    # Compare
    results = compare_costs(csv_costs, shopify_variants)

    matches = results["matches"]
    mismatches = results["mismatches"]
    csv_only = results["csv_only"]
    shopify_only = results["shopify_only"]

    # Summary
    print("=" * 70)
    print("Summary:")
    print(f"   CSV SKUs (with cost):  {len(csv_costs)}")
    print(f"   Shopify SKUs:          {len(shopify_variants)}")
    print(f"   Cost matches:          {len(matches)}")
    print(f"   Cost mismatches:       {len(mismatches)}")
    print(f"   In CSV only:           {len(csv_only)}")
    print(f"   In Shopify only:       {len(shopify_only)}")
    print("=" * 70)
    print()

    # Detail: mismatches
    if mismatches:
        def _fmt_cost(val):
            if val is None:
                return "not set"
            return f"${val:.2f}"

        print(f"Cost mismatches ({len(mismatches)}):")
        for m in mismatches:
            option = m.get("option", "")
            option_str = f"  ({option})" if option else ""
            print(
                f"   {m['sku']:25}  CSV {_fmt_cost(m['csv_cost']):>10}"
                f"   Shopify {_fmt_cost(m['shopify_cost']):>10}"
                f"{option_str}"
            )
        print()

    # Detail: CSV only
    if csv_only:
        print(f"In CSV but not in Shopify ({len(csv_only)}):")
        for sku in csv_only:
            print(f"   {sku}")
        print()

    # Detail: Shopify only
    if shopify_only:
        print(f"In Shopify but not in CSV ({len(shopify_only)}):")
        for sku in shopify_only:
            cost = shopify_variants[sku]["cost"]
            cost_str = f"${cost:.2f}" if cost is not None else "not set"
            print(f"   {sku:25}  cost: {cost_str}")
        print()

    if not mismatches:
        print("All matched SKUs have correct costs!")
        return 0

    if not args.fix:
        print(f"Run with --fix to update {len(mismatches)} Shopify variant costs.")
        print(f"   Command: python util/wire_cost_sync.py --fix")
        return 0

    # Apply fixes
    print(f"Updating {len(mismatches)} variant costs in Shopify...")
    print()

    fixed = 0
    failed = 0

    for m in mismatches:
        ok, err = update_variant_cost(m["product_id"], m["variant_id"], m["csv_cost"])

        if ok:
            print(f"   OK   {m['sku']:25}  cost=${m['csv_cost']:.2f}")
            fixed += 1
        else:
            print(f"   FAIL {m['sku']}: {err}")
            failed += 1

    print()
    print("=" * 70)
    print(f"Done! Updated: {fixed}  Failed: {failed}")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
