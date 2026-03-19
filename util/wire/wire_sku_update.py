#!/usr/bin/env python3
"""
Batch 1: Update existing wire variant SKUs in Shopify.

Reads old_sku -> new sku mappings from the price update CSV and renames
each variant in the Wire Shopify store using productVariantsBulkUpdate.

Usage:
    python util/wire/wire_sku_update.py                    # Preview changes
    python util/wire/wire_sku_update.py --fix              # Apply SKU updates
    python util/wire/wire_sku_update.py --fix --batch 50   # Limit to first N
"""

import sys
import csv
import json
import time
import argparse
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import shopify
from greenlight.shopify_client import get_wire_shopify_session, close_shopify_session

CSV_PATH = Path(__file__).parent.parent.parent / "data" / "imports" / "031726_wire_sku_price_update.csv"


def load_sku_mappings():
    """Load old_sku -> new_sku mappings from CSV.

    Only returns rows where old_sku is present (existing variants).
    """
    mappings = {}
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            old = (row.get("old_sku") or "").strip()
            new = (row.get("sku") or "").strip()
            if old and new and old != new:
                mappings[old] = new
    return mappings


def fetch_wire_variants():
    """Fetch all wire variants from Shopify with their current SKUs.

    Returns dict: sku -> {variant_id, product_id, sku}
    """
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
                    title
                    variants(first: 100) {
                        edges {
                            node {
                                id
                                sku
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
            title = product.get("title", "")

            for v_edge in product.get("variants", {}).get("edges", []):
                v = v_edge["node"]
                sku = (v.get("sku") or "").strip()
                if not sku:
                    continue
                variants[sku] = {
                    "variant_id": v["id"],
                    "product_id": product_id,
                    "title": title,
                }

        has_next_page = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")

    close_shopify_session()
    return variants


def update_skus_for_product(product_id, variant_updates):
    """Update SKUs for variants on a single product.

    variant_updates: list of {variant_id, new_sku}
    Returns (success_count, errors)
    """
    session = get_wire_shopify_session()

    mutation = """
    mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
        productVariantsBulkUpdate(productId: $productId, variants: $variants) {
            productVariants { id sku }
            userErrors { field message }
        }
    }
    """

    variables = {
        "productId": product_id,
        "variants": [
            {"id": v["variant_id"], "inventoryItem": {"sku": v["new_sku"]}}
            for v in variant_updates
        ],
    }

    result = shopify.GraphQL().execute(mutation, variables=variables)
    data = json.loads(result)
    close_shopify_session()

    if "errors" in data:
        return 0, [str(data["errors"])]

    mutation_data = data.get("data", {}).get("productVariantsBulkUpdate", {})
    user_errors = mutation_data.get("userErrors", [])

    if user_errors:
        return 0, [e["message"] for e in user_errors]

    updated = mutation_data.get("productVariants", [])
    return len(updated), []


def main():
    parser = argparse.ArgumentParser(description="Batch 1: Update existing wire SKUs in Shopify")
    parser.add_argument("--fix", action="store_true", help="Apply SKU updates (default: preview only)")
    parser.add_argument("--batch", type=int, default=0, help="Limit to first N products (0 = all)")
    args = parser.parse_args()

    print("Wire SKU Update (Batch 1)")
    print("=" * 70)
    print()

    # Load mappings from CSV
    print("Loading SKU mappings from CSV...")
    mappings = load_sku_mappings()
    print(f"  {len(mappings)} SKU renames to apply")
    print()

    # Fetch current Shopify variants
    print("Fetching variants from Shopify Wire store...")
    shopify_variants = fetch_wire_variants()
    print(f"  {len(shopify_variants)} total variants in Shopify")
    print()

    # Match CSV mappings to Shopify variants
    matched = []
    not_found = []
    already_done = []

    for old_sku, new_sku in sorted(mappings.items()):
        if old_sku in shopify_variants:
            matched.append({
                "old_sku": old_sku,
                "new_sku": new_sku,
                "variant_id": shopify_variants[old_sku]["variant_id"],
                "product_id": shopify_variants[old_sku]["product_id"],
                "title": shopify_variants[old_sku]["title"],
            })
        elif new_sku in shopify_variants:
            # Already renamed
            already_done.append(old_sku)
        else:
            not_found.append(old_sku)

    # Group by product for bulk updates
    by_product = defaultdict(list)
    for m in matched:
        by_product[m["product_id"]].append(m)

    # Summary
    print("=" * 70)
    print("Summary:")
    print(f"  SKUs to rename:      {len(matched)} (across {len(by_product)} products)")
    print(f"  Already renamed:     {len(already_done)}")
    print(f"  Not found in Shopify:{len(not_found)}")
    print("=" * 70)
    print()

    if not_found:
        print(f"Not found in Shopify ({len(not_found)}):")
        for sku in not_found[:20]:
            print(f"  {sku} -> {mappings[sku]}")
        if len(not_found) > 20:
            print(f"  ... and {len(not_found) - 20} more")
        print()

    if already_done:
        print(f"Already renamed ({len(already_done)}):")
        for sku in already_done[:10]:
            print(f"  {sku} -> {mappings[sku]}")
        if len(already_done) > 10:
            print(f"  ... and {len(already_done) - 10} more")
        print()

    # Preview some changes
    if matched:
        print(f"Sample changes:")
        for m in matched[:10]:
            print(f"  {m['old_sku']:25} -> {m['new_sku']:25} ({m['title'][:40]})")
        if len(matched) > 10:
            print(f"  ... and {len(matched) - 10} more")
        print()

    if not matched:
        print("Nothing to update!")
        return 0

    if not args.fix:
        print(f"Run with --fix to apply {len(matched)} SKU renames.")
        return 0

    # Apply updates, grouped by product
    products = list(by_product.items())
    if args.batch:
        products = products[:args.batch]
        print(f"Limiting to first {args.batch} products")
        print()

    print(f"Updating {sum(len(v) for _, v in products)} SKUs across {len(products)} products...")
    print()

    total_ok = 0
    total_fail = 0

    for i, (product_id, variants) in enumerate(products, 1):
        title = variants[0]["title"][:40]
        count, errors = update_skus_for_product(
            product_id,
            [{"variant_id": v["variant_id"], "new_sku": v["new_sku"]} for v in variants],
        )

        if errors:
            print(f"  [{i}/{len(products)}] FAIL  {title}")
            for err in errors:
                print(f"           {err}")
            total_fail += len(variants)
        else:
            skus = ", ".join(v["new_sku"] for v in variants)
            print(f"  [{i}/{len(products)}] OK    {title} ({count} variants: {skus})")
            total_ok += count

        # Respect Shopify rate limits
        time.sleep(0.5)

    print()
    print("=" * 70)
    print(f"Done! Updated: {total_ok}  Failed: {total_fail}")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
