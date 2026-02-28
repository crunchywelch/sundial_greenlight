#!/usr/bin/env python3
"""
Audit and fix the "continue selling when out of stock" policy on wire variants.

Rules:
  - By-the-foot SKUs (ending in F): should be CONTINUE (always sellable)
  - Spool SKUs (ending in S or L): should be DENY (stop when out of stock)

Usage:
    python util/audit_inventory_policy.py          # Preview mismatches
    python util/audit_inventory_policy.py --fix    # Fix mismatches in Shopify
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import shopify
from greenlight.shopify_client import get_wire_shopify_session, close_shopify_session


def expected_policy(sku):
    """Determine expected inventory policy from SKU suffix.

    Returns 'CONTINUE', 'DENY', or None if not a wire SKU we handle.
    """
    if not sku.startswith("W"):
        return None
    if sku.endswith("F"):
        return "CONTINUE"
    elif sku.endswith("S") or sku.endswith("L"):
        return "DENY"
    return None


def fetch_wire_variants():
    """Fetch all wire variants with their inventory policy."""
    try:
        session = get_wire_shopify_session()

        variants = []
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
                                    inventoryPolicy
                                    inventoryQuantity
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
                product_id = product["id"]

                for v_edge in product.get("variants", {}).get("edges", []):
                    v = v_edge["node"]
                    sku = (v.get("sku") or "").strip()
                    if not sku or not sku.startswith("W"):
                        continue

                    variants.append({
                        "sku": sku,
                        "variant_id": v["id"],
                        "product_id": product_id,
                        "policy": v.get("inventoryPolicy", ""),
                        "qty": v.get("inventoryQuantity", 0),
                    })

            has_next_page = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")

        return variants

    except Exception as e:
        print(f"  Error fetching variants: {e}")
        return []
    finally:
        close_shopify_session()


def update_variant_policy(product_id, variant_id, policy):
    """Update a variant's inventory policy."""
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
                "inventoryPolicy": policy,
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
        description="Audit and fix wire variant inventory policies"
    )
    parser.add_argument("--fix", action="store_true",
                        help="Fix mismatched policies in Shopify")
    args = parser.parse_args()

    print("Wire Variant Inventory Policy Audit")
    print("=" * 70)
    print("  Rule: by-the-foot (F suffix) → CONTINUE")
    print("  Rule: spool (S/L suffix)     → DENY")
    print()

    print("Fetching wire variants from Shopify...")
    variants = fetch_wire_variants()
    print(f"  {len(variants)} wire variants")
    print()

    matches = []
    mismatches = []
    skipped = []

    for v in variants:
        want = expected_policy(v["sku"])
        if want is None:
            skipped.append(v)
            continue

        if v["policy"] == want:
            matches.append(v)
        else:
            v["expected"] = want
            mismatches.append(v)

    # Summary
    print("=" * 70)
    print(f"  Correct:    {len(matches)}")
    print(f"  Mismatched: {len(mismatches)}")
    print(f"  Skipped:    {len(skipped)} (no F/S/L suffix)")
    print("=" * 70)
    print()

    if mismatches:
        # Group by type of mismatch
        foot_should_continue = [m for m in mismatches if m["expected"] == "CONTINUE"]
        spool_should_deny = [m for m in mismatches if m["expected"] == "DENY"]

        if foot_should_continue:
            print(f"By-the-foot SKUs that should be CONTINUE ({len(foot_should_continue)}):")
            for m in sorted(foot_should_continue, key=lambda x: x["sku"]):
                print(f"  {m['sku']:25} currently {m['policy']:10} qty={m['qty']}")
            print()

        if spool_should_deny:
            print(f"Spool SKUs that should be DENY ({len(spool_should_deny)}):")
            for m in sorted(spool_should_deny, key=lambda x: x["sku"]):
                print(f"  {m['sku']:25} currently {m['policy']:10} qty={m['qty']}")
            print()

    if not mismatches:
        print("All wire variants have correct inventory policies!")
        return 0

    if not args.fix:
        print(f"Run with --fix to update {len(mismatches)} variants.")
        return 0

    # Apply fixes
    print(f"Updating {len(mismatches)} variant policies in Shopify...")
    print()

    fixed = 0
    failed = 0

    for m in sorted(mismatches, key=lambda x: x["sku"]):
        ok, err = update_variant_policy(
            m["product_id"], m["variant_id"], m["expected"]
        )
        if ok:
            print(f"  OK   {m['sku']:25} {m['policy']} → {m['expected']}")
            fixed += 1
        else:
            print(f"  FAIL {m['sku']}: {err}")
            failed += 1

    print()
    print("=" * 70)
    print(f"Done! Updated: {fixed}  Failed: {failed}")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
