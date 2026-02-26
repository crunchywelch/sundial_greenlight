#!/usr/bin/env python3
"""
Compare and sync non-wire product costs to the Sundial Wire Shopify store.

Reads the consolidated cost CSV (docs/nonwire_costs.csv) and compares against
current Shopify variant costs. Reports differences and optionally updates
Shopify to match.

The cost CSV is the source of truth, built from:
  - Satco PO costs (PO 1011, PO 1013)
  - Satco negotiated price sheet (customer SUNNMA0)
  - B&P Lamp Supply pricing
  - Catalog-based estimates with vendor discount ratios

Usage:
    python util/nonwire_cost_sync.py           # Preview differences
    python util/nonwire_cost_sync.py --fix     # Update Shopify to match CSV
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

CSV_PATH = Path(__file__).parent.parent / "docs" / "nonwire_costs.csv"


def load_csv_costs(csv_path):
    """Parse the non-wire cost CSV into a dict of SKU -> {cost, vendor, notes}.

    Skips comment lines (starting with #) and blank rows.
    """
    sku_costs = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        lines = [line for line in f if not line.startswith("#")]

    reader = csv.DictReader(lines)
    for row in reader:
        sku = (row.get("SKU") or "").strip()
        cost_str = (row.get("Cost") or "").strip()
        if not sku or not cost_str:
            continue
        try:
            sku_costs[sku] = {
                "cost": float(cost_str),
                "vendor": (row.get("Vendor") or "").strip(),
                "notes": (row.get("Notes") or "").strip(),
            }
        except ValueError:
            continue
    return sku_costs


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


def compare_costs(csv_costs, shopify_variants):
    """Compare CSV costs against Shopify and categorize results."""
    csv_skus = set(csv_costs.keys())
    shopify_skus = set(shopify_variants.keys())

    matches = []
    mismatches = []

    for sku in sorted(csv_skus & shopify_skus):
        csv_cost = csv_costs[sku]["cost"]
        vendor = csv_costs[sku]["vendor"]
        notes = csv_costs[sku]["notes"]
        shopify_cost = shopify_variants[sku]["cost"]

        if shopify_cost is not None and abs(csv_cost - shopify_cost) <= 0.01:
            matches.append(sku)
        else:
            mismatches.append({
                "sku": sku,
                "vendor": vendor,
                "notes": notes,
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
        "--fix", action="store_true", help="Update Shopify costs to match CSV"
    )
    args = parser.parse_args()

    print("Non-Wire Product Cost Sync")
    print("=" * 80)
    print()

    # Load CSV costs
    print(f"Loading costs from {CSV_PATH.name}...")
    csv_costs = load_csv_costs(CSV_PATH)
    print(f"   {len(csv_costs)} SKUs with cost data")
    print()

    # Fetch Shopify data
    print("Fetching non-wire variants from Shopify...")
    shopify_variants = fetch_nonwire_variants()
    print(f"   {len(shopify_variants)} non-wire variants from Shopify")
    print()

    # Compare
    results = compare_costs(csv_costs, shopify_variants)

    matches = results["matches"]
    mismatches = results["mismatches"]
    csv_only = results["csv_only"]
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
                f"   {m['sku']:25}  CSV {_fmt_cost(m['csv_cost']):>10}"
                f"   Shopify {_fmt_cost(m['shopify_cost']):>10}"
                f"   [{m['vendor']}]"
            )
        print()

    # Detail: CSV only
    if csv_only:
        print(f"In CSV but not in Shopify ({len(csv_only)}):")
        for sku in csv_only:
            print(f"   {sku}")
        print()

    # Summary
    print("=" * 80)
    print(f"CSV SKUs:           {len(csv_costs)}")
    print(f"Shopify non-wire:   {len(shopify_variants)}")
    print(f"Cost matches:       {len(matches)}")
    print(f"Cost differences:   {len(mismatches)}")
    print(f"In CSV only:        {len(csv_only)}")
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
        ok, err = update_variant_cost(m["product_id"], m["variant_id"], m["csv_cost"])

        if ok:
            prev = _fmt_cost(m["shopify_cost"])
            print(f"   OK   {m['sku']:25}  {prev:>10} -> ${m['csv_cost']:.2f}")
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
