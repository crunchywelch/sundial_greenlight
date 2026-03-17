#!/usr/bin/env python3
"""
Batch 2: Create new wire variants in Shopify.

Reads the price update CSV for rows with empty old_sku (new variants),
finds the parent product via a sibling SKU, and creates the variant
using productVariantsBulkCreate.

Usage:
    python util/wire/wire_add_variants.py                    # Preview
    python util/wire/wire_add_variants.py --fix              # Create variants
    python util/wire/wire_add_variants.py --fix --batch 5    # First N products
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

OPTION_NAME = "Buy by the foot or spool"


def load_new_variants():
    """Load new variants (empty old_sku) from CSV.

    Returns list of dicts grouped by title.
    """
    by_title = defaultdict(list)
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            old = (row.get("old_sku") or "").strip()
            if old:
                continue  # Existing variant, skip
            sku = (row.get("sku") or "").strip()
            if not sku:
                continue
            title = row.get("title", "").strip()
            option = row.get("option", "").strip()
            by_title[title].append({
                "sku": sku,
                "option": option,
                "title": title,
            })
    return by_title


def load_sibling_skus():
    """Load existing SKUs (with old_sku) from CSV, keyed by title.

    Used to find the parent product in Shopify.
    """
    by_title = defaultdict(list)
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            old = (row.get("old_sku") or "").strip()
            if not old:
                continue
            sku = (row.get("sku") or "").strip()
            title = row.get("title", "").strip()
            by_title[title].append(sku)
    return by_title


def fetch_wire_variants():
    """Fetch all wire variants from Shopify.

    Returns dict: sku -> {variant_id, product_id, title, option_id}
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
                    options {
                        id
                        name
                    }
                    variants(first: 100) {
                        edges {
                            node {
                                id
                                sku
                                selectedOptions { name value }
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

            # Find the spool option ID
            option_id = None
            for opt in product.get("options", []):
                if opt["name"] == OPTION_NAME:
                    option_id = opt["id"]
                    break

            for v_edge in product.get("variants", {}).get("edges", []):
                v = v_edge["node"]
                sku = (v.get("sku") or "").strip()
                if not sku:
                    continue
                variants[sku] = {
                    "variant_id": v["id"],
                    "product_id": product_id,
                    "title": title,
                    "option_id": option_id,
                }

        has_next_page = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")

    close_shopify_session()
    return variants


def create_variants_for_product(product_id, option_id, new_variants):
    """Create new variants on a product.

    new_variants: list of {sku, option}
    Returns (success_count, errors)
    """
    session = get_wire_shopify_session()

    mutation = """
    mutation productVariantsBulkCreate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
        productVariantsBulkCreate(productId: $productId, variants: $variants) {
            productVariants { id }
            userErrors { field message }
        }
    }
    """

    variant_inputs = []
    for v in new_variants:
        variant_input = {
            "inventoryItem": {"sku": v["sku"]},
            "optionValues": [
                {
                    "optionId": option_id,
                    "name": v["option"],
                }
            ],
        }
        variant_inputs.append(variant_input)

    variables = {
        "productId": product_id,
        "variants": variant_inputs,
    }

    result = shopify.GraphQL().execute(mutation, variables=variables)
    data = json.loads(result)
    close_shopify_session()

    if "errors" in data:
        return 0, [str(data["errors"])]

    mutation_data = data.get("data", {}).get("productVariantsBulkCreate", {})
    user_errors = mutation_data.get("userErrors", [])

    if user_errors:
        return 0, [f"{e.get('field', '?')}: {e['message']}" for e in user_errors]

    created = mutation_data.get("productVariants", [])
    return len(created), []


def main():
    parser = argparse.ArgumentParser(description="Batch 2: Create new wire variants in Shopify")
    parser.add_argument("--fix", action="store_true", help="Create variants (default: preview only)")
    parser.add_argument("--batch", type=int, default=0, help="Limit to first N products (0 = all)")
    args = parser.parse_args()

    print("Wire Add Variants (Batch 2)")
    print("=" * 70)
    print()

    # Load new variants from CSV
    print("Loading new variants from CSV...")
    new_by_title = load_new_variants()
    total_new = sum(len(v) for v in new_by_title.values())
    print(f"  {total_new} new variants across {len(new_by_title)} products")

    # Load sibling SKUs for product lookup
    sibling_skus = load_sibling_skus()
    print()

    # Fetch current Shopify state
    print("Fetching variants from Shopify Wire store...")
    shopify_variants = fetch_wire_variants()
    print(f"  {len(shopify_variants)} total variants in Shopify")
    print()

    # Match each product's new variants to a Shopify product
    to_create = []  # list of {product_id, option_id, title, variants: [{sku, option}]}
    already_exist = []
    no_parent = []

    for title, new_vars in sorted(new_by_title.items()):
        # Check which ones already exist in Shopify
        remaining = []
        for v in new_vars:
            if v["sku"] in shopify_variants:
                already_exist.append(v["sku"])
            else:
                remaining.append(v)

        if not remaining:
            continue

        # Find parent product via sibling SKU
        siblings = sibling_skus.get(title, [])
        product_id = None
        option_id = None

        for sib_sku in siblings:
            if sib_sku in shopify_variants:
                product_id = shopify_variants[sib_sku]["product_id"]
                option_id = shopify_variants[sib_sku]["option_id"]
                break

        if not product_id:
            no_parent.extend(remaining)
            continue

        if not option_id:
            print(f"  WARNING: No '{OPTION_NAME}' option found on product: {title}")
            no_parent.extend(remaining)
            continue

        to_create.append({
            "product_id": product_id,
            "option_id": option_id,
            "title": title,
            "variants": remaining,
        })

    # Summary
    create_count = sum(len(p["variants"]) for p in to_create)
    print("=" * 70)
    print("Summary:")
    print(f"  Variants to create:  {create_count} (across {len(to_create)} products)")
    print(f"  Already exist:       {len(already_exist)}")
    print(f"  No parent found:     {len(no_parent)}")
    print("=" * 70)
    print()

    if no_parent:
        print(f"No parent product found ({len(no_parent)}):")
        for v in no_parent[:10]:
            print(f"  {v['sku']:25} {v['title'][:45]}")
        if len(no_parent) > 10:
            print(f"  ... and {len(no_parent) - 10} more")
        print()

    if already_exist:
        print(f"Already exist ({len(already_exist)}):")
        for sku in already_exist[:10]:
            print(f"  {sku}")
        if len(already_exist) > 10:
            print(f"  ... and {len(already_exist) - 10} more")
        print()

    # Preview
    if to_create:
        print("Sample creations:")
        for p in to_create[:5]:
            print(f"  {p['title'][:50]}")
            for v in p["variants"]:
                print(f"    + {v['sku']:25} ({v['option']})")
        if len(to_create) > 5:
            print(f"  ... and {len(to_create) - 5} more products")
        print()

    if not to_create:
        print("Nothing to create!")
        return 0

    if not args.fix:
        print(f"Run with --fix to create {create_count} new variants.")
        return 0

    # Apply
    products = to_create
    if args.batch:
        products = products[:args.batch]
        print(f"Limiting to first {args.batch} products")
        print()

    total_ok = 0
    total_fail = 0

    print(f"Creating variants across {len(products)} products...")
    print()

    for i, p in enumerate(products, 1):
        count, errors = create_variants_for_product(
            p["product_id"], p["option_id"], p["variants"]
        )

        if errors:
            print(f"  [{i}/{len(products)}] FAIL  {p['title'][:40]}")
            for err in errors:
                print(f"           {err}")
            total_fail += len(p["variants"])
        else:
            skus = ", ".join(v["sku"] for v in p["variants"])
            print(f"  [{i}/{len(products)}] OK    {p['title'][:40]} (+{count}: {skus})")
            total_ok += count

        time.sleep(0.5)

    print()
    print("=" * 70)
    print(f"Done! Created: {total_ok}  Failed: {total_fail}")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
