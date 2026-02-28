#!/usr/bin/env python3
"""
Compare and sync wire inventory quantities from a physical audit CSV to Shopify.

Reads the physical inventory audit CSV (data/imports/022026_wire_inventory_audit.csv),
compares "Qty (real)" values against current Shopify quantities, and optionally
pushes corrections.

Usage:
    python util/wire/wire_inventory_sync.py           # Preview differences
    python util/wire/wire_inventory_sync.py --fix     # Update Shopify to match audit
"""

import sys
import csv
import json
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import shopify
from greenlight.shopify_client import get_wire_shopify_session, close_shopify_session

CSV_PATH = Path(__file__).parent.parent.parent / "data" / "imports" / "022026_wire_inventory_audit.csv"
SKIP_SKUS = {"WCUTMX18MX10", "WIRECHNG"}


def load_audit_quantities():
    """Load SKU -> real quantity from the audit CSV.

    Returns dict of SKU -> int quantity for rows where "Qty (real)" is non-empty.
    """
    quantities = {}
    with open(CSV_PATH, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sku = row["SKU"].strip()
            qty_real = row["Qty (real)"].strip()
            if not sku or not qty_real:
                continue
            quantities[sku] = int(qty_real)
    return quantities


def fetch_wire_variants():
    """Fetch all variants from the Wire Shopify store with inventory data.

    Returns dict mapping SKU -> {inventory_item_id, shopify_qty}.
    """
    try:
        session = get_wire_shopify_session()

        variants = {}
        has_next_page = True
        cursor = None

        query = """
        query getProducts($limit: Int!, $cursor: String) {
            products(first: $limit, after: $cursor, query: "status:active") {
                pageInfo { hasNextPage endCursor }
                edges {
                    node {
                        variants(first: 100) {
                            edges {
                                node {
                                    sku
                                    inventoryQuantity
                                    inventoryItem {
                                        id
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
                for v_edge in edge["node"].get("variants", {}).get("edges", []):
                    v = v_edge["node"]
                    sku = (v.get("sku") or "").strip()
                    if not sku or not sku.startswith("W") or sku in SKIP_SKUS:
                        continue

                    inv = v.get("inventoryItem") or {}
                    variants[sku] = {
                        "inventory_item_id": inv.get("id"),
                        "shopify_qty": v.get("inventoryQuantity", 0),
                    }

            has_next_page = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")

        return variants

    except Exception as e:
        print(f"   Error fetching wire store variants: {e}")
        return {}
    finally:
        close_shopify_session()


def get_location_id():
    """Get the primary location ID for the Wire Shopify store."""
    try:
        session = get_wire_shopify_session()
        query = "{ locations(first: 1) { edges { node { id } } } }"
        result = shopify.GraphQL().execute(query)
        data = json.loads(result)

        if "errors" in data:
            print(f"   GraphQL errors fetching location: {data['errors']}")
            return None

        edges = data.get("data", {}).get("locations", {}).get("edges", [])
        if edges:
            return edges[0]["node"]["id"]
        return None
    except Exception as e:
        print(f"   Error fetching location ID: {e}")
        return None
    finally:
        close_shopify_session()


def compare_quantities(audit_qtys, shopify_variants):
    """Compare audit quantities against Shopify and categorize results."""
    audit_skus = set(audit_qtys.keys())
    shopify_skus = set(shopify_variants.keys())

    matches = []
    mismatches = []

    for sku in sorted(audit_skus & shopify_skus):
        real_qty = audit_qtys[sku]
        shopify_qty = shopify_variants[sku]["shopify_qty"]

        if real_qty == shopify_qty:
            matches.append(sku)
        else:
            mismatches.append({
                "sku": sku,
                "real_qty": real_qty,
                "shopify_qty": shopify_qty,
                "inventory_item_id": shopify_variants[sku]["inventory_item_id"],
            })

    return {
        "matches": matches,
        "mismatches": mismatches,
        "audit_only": sorted(audit_skus - shopify_skus),
        "shopify_only": sorted(shopify_skus - audit_skus),
    }


def set_inventory_quantity(inventory_item_id, location_id, quantity):
    """Set Shopify inventory for a single item."""
    try:
        session = get_wire_shopify_session()
        mutation = """
        mutation inventorySetQuantities($input: InventorySetQuantitiesInput!) {
            inventorySetQuantities(input: $input) {
                userErrors {
                    field
                    message
                }
                inventoryAdjustmentGroup {
                    changes {
                        name
                        delta
                    }
                }
            }
        }
        """
        variables = {
            "input": {
                "reason": "correction",
                "name": "available",
                "ignoreCompareQuantity": True,
                "quantities": [
                    {
                        "inventoryItemId": inventory_item_id,
                        "locationId": location_id,
                        "quantity": quantity,
                    }
                ],
            }
        }
        result = shopify.GraphQL().execute(mutation, variables=variables)
        data = json.loads(result)

        if "errors" in data:
            return False, str(data["errors"])

        user_errors = (
            data.get("data", {})
            .get("inventorySetQuantities", {})
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
        description="Compare and sync Wire store inventory from audit CSV to Shopify"
    )
    parser.add_argument(
        "--fix", action="store_true", help="Update Shopify quantities to match audit"
    )
    args = parser.parse_args()

    print("Wire Store Inventory Sync")
    print("=" * 70)
    print()

    # Load audit CSV
    print(f"Loading audit data from {CSV_PATH.name}...")
    audit_qtys = load_audit_quantities()
    print(f"   {len(audit_qtys)} SKUs with real quantities")
    print()

    # Fetch Shopify data
    print("Fetching Wire store variants...")
    shopify_variants = fetch_wire_variants()
    print(f"   {len(shopify_variants)} variants from Shopify")
    print()

    # Compare
    results = compare_quantities(audit_qtys, shopify_variants)

    matches = results["matches"]
    mismatches = results["mismatches"]
    audit_only = results["audit_only"]
    shopify_only = results["shopify_only"]

    # Summary
    print("=" * 70)
    print("Summary:")
    print(f"   Audit SKUs:            {len(audit_qtys)}")
    print(f"   Shopify SKUs:          {len(shopify_variants)}")
    print(f"   Quantity matches:      {len(matches)}")
    print(f"   Quantity mismatches:   {len(mismatches)}")
    print(f"   In audit only:         {len(audit_only)}")
    print(f"   In Shopify only:       {len(shopify_only)}")
    print("=" * 70)
    print()

    # Detail: mismatches
    if mismatches:
        print(f"Quantity mismatches ({len(mismatches)}):")
        for m in mismatches:
            diff = m["real_qty"] - m["shopify_qty"]
            sign = "+" if diff > 0 else ""
            print(
                f"   {m['sku']:25}  Shopify {m['shopify_qty']:>7}"
                f"   Audit {m['real_qty']:>7}"
                f"   ({sign}{diff})"
            )
        print()

    # Detail: audit only
    if audit_only:
        print(f"In audit but not in Shopify ({len(audit_only)}):")
        for sku in audit_only:
            print(f"   {sku}")
        print()

    # Detail: Shopify only
    if shopify_only:
        print(f"In Shopify but not in audit ({len(shopify_only)}):")
        for sku in shopify_only:
            qty = shopify_variants[sku]["shopify_qty"]
            print(f"   {sku:25}  qty: {qty}")
        print()

    if not mismatches:
        print("All matched SKUs have correct quantities!")
        return 0

    if not args.fix:
        print(f"Run with --fix to update {len(mismatches)} Shopify quantities.")
        print(f"   Command: python util/wire/wire_inventory_sync.py --fix")
        return 0

    # Get location ID for inventory updates
    print("Fetching location ID...")
    location_id = get_location_id()
    if not location_id:
        print("   ERROR: Could not determine Shopify location")
        return 1
    print(f"   Location: {location_id}")
    print()

    # Apply fixes
    print(f"Updating {len(mismatches)} variant quantities in Shopify...")
    print()

    fixed = 0
    failed = 0

    for m in mismatches:
        ok, err = set_inventory_quantity(
            m["inventory_item_id"], location_id, m["real_qty"]
        )

        if ok:
            print(f"   OK   {m['sku']:25}  {m['shopify_qty']} -> {m['real_qty']}")
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
