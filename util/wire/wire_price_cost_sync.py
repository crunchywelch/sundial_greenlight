#!/usr/bin/env python3
"""
Batch 3: Update prices and costs for all wire variants in Shopify.

Reads prop price and total cost from the CSV and updates each variant
in the Wire Shopify store using productVariantsBulkUpdate.

Usage:
    python util/wire/wire_price_cost_sync.py                    # Preview
    python util/wire/wire_price_cost_sync.py --fix              # Apply updates
    python util/wire/wire_price_cost_sync.py --fix --batch 5    # First N products
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


def parse_price(val):
    """Parse a price string, handling commas, parens (negatives), and empty values."""
    if not val or not val.strip():
        return None
    val = val.strip().replace(",", "").replace("$", "")
    if val.startswith("(") and val.endswith(")"):
        val = "-" + val[1:-1]
    try:
        return round(float(val), 2)
    except ValueError:
        return None


def load_csv_pricing():
    """Load SKU -> {price, cost} from CSV.

    Returns dict: sku -> {price, cost}
    """
    pricing = {}
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sku = (row.get("sku") or "").strip()
            if not sku:
                continue
            price = parse_price(row.get("prop price"))
            cost = parse_price(row.get("total cost"))
            if price is None:
                continue
            pricing[sku] = {"price": price, "cost": cost}
    return pricing


def fetch_wire_variants():
    """Fetch all wire variants with current price and cost.

    Returns dict: sku -> {variant_id, product_id, title, price, cost}
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
                                price
                                inventoryItem {
                                    unitCost { amount }
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
            product_id = product["id"]
            title = product.get("title", "")

            for v_edge in product.get("variants", {}).get("edges", []):
                v = v_edge["node"]
                sku = (v.get("sku") or "").strip()
                if not sku:
                    continue

                inv = v.get("inventoryItem") or {}
                unit_cost = inv.get("unitCost") or {}
                cost_amt = unit_cost.get("amount")

                variants[sku] = {
                    "variant_id": v["id"],
                    "product_id": product_id,
                    "title": title,
                    "price": float(v["price"]) if v.get("price") else None,
                    "cost": float(cost_amt) if cost_amt else None,
                }

        has_next_page = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")

    close_shopify_session()
    return variants


def update_variants_for_product(product_id, variant_updates):
    """Update price and cost for variants on a single product.

    variant_updates: list of {variant_id, price, cost}
    Returns (success_count, errors)
    """
    session = get_wire_shopify_session()

    mutation = """
    mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
        productVariantsBulkUpdate(productId: $productId, variants: $variants) {
            productVariants { id }
            userErrors { field message }
        }
    }
    """

    variant_inputs = []
    for v in variant_updates:
        vi = {
            "id": v["variant_id"],
            "price": str(v["price"]),
        }
        if v["cost"] is not None:
            vi["inventoryItem"] = {"cost": v["cost"]}
        variant_inputs.append(vi)

    variables = {
        "productId": product_id,
        "variants": variant_inputs,
    }

    result = shopify.GraphQL().execute(mutation, variables=variables)
    data = json.loads(result)
    close_shopify_session()

    if "errors" in data:
        return 0, [str(data["errors"])]

    mutation_data = data.get("data", {}).get("productVariantsBulkUpdate", {})
    user_errors = mutation_data.get("userErrors", [])

    if user_errors:
        return 0, [f"{e.get('field', '?')}: {e['message']}" for e in user_errors]

    updated = mutation_data.get("productVariants", [])
    return len(updated), []


def main():
    parser = argparse.ArgumentParser(description="Batch 3: Update wire prices and costs in Shopify")
    parser.add_argument("--fix", action="store_true", help="Apply updates (default: preview only)")
    parser.add_argument("--batch", type=int, default=0, help="Limit to first N products (0 = all)")
    args = parser.parse_args()

    print("Wire Price & Cost Sync (Batch 3)")
    print("=" * 70)
    print()

    # Load CSV pricing
    print("Loading pricing from CSV...")
    csv_pricing = load_csv_pricing()
    print(f"  {len(csv_pricing)} SKUs with pricing data")
    print()

    # Fetch Shopify state
    print("Fetching variants from Shopify Wire store...")
    shopify_variants = fetch_wire_variants()
    print(f"  {len(shopify_variants)} total variants in Shopify")
    print()

    # Compare and find what needs updating
    price_changes = []
    cost_changes = []
    already_correct = []
    not_in_shopify = []

    for sku, csv_data in sorted(csv_pricing.items()):
        if sku not in shopify_variants:
            not_in_shopify.append(sku)
            continue

        sv = shopify_variants[sku]
        price_match = sv["price"] is not None and abs(sv["price"] - csv_data["price"]) <= 0.01
        cost_match = (
            (sv["cost"] is not None and csv_data["cost"] is not None and abs(sv["cost"] - csv_data["cost"]) <= 0.01)
            or (sv["cost"] is None and csv_data["cost"] is None)
        )

        if price_match and cost_match:
            already_correct.append(sku)
        else:
            if not price_match:
                price_changes.append(sku)
            if not cost_match:
                cost_changes.append(sku)

    # Build update list (unique SKUs that need either price or cost change)
    needs_update_skus = set(price_changes) | set(cost_changes)

    # Group by product
    by_product = defaultdict(list)
    for sku in needs_update_skus:
        sv = shopify_variants[sku]
        by_product[sv["product_id"]].append({
            "sku": sku,
            "variant_id": sv["variant_id"],
            "price": csv_pricing[sku]["price"],
            "cost": csv_pricing[sku]["cost"],
            "old_price": sv["price"],
            "old_cost": sv["cost"],
            "title": sv["title"],
        })

    # Summary
    print("=" * 70)
    print("Summary:")
    print(f"  Already correct:     {len(already_correct)}")
    print(f"  Price changes:       {len(price_changes)}")
    print(f"  Cost changes:        {len(cost_changes)}")
    print(f"  Total to update:     {len(needs_update_skus)} variants across {len(by_product)} products")
    print(f"  Not in Shopify:      {len(not_in_shopify)}")
    print("=" * 70)
    print()

    if not_in_shopify:
        print(f"Not found in Shopify ({len(not_in_shopify)}):")
        for sku in not_in_shopify[:10]:
            print(f"  {sku}")
        if len(not_in_shopify) > 10:
            print(f"  ... and {len(not_in_shopify) - 10} more")
        print()

    # Preview some changes
    def _fmt(val):
        return f"${val:.2f}" if val is not None else "not set"

    if needs_update_skus:
        print("Sample changes:")
        shown = 0
        for sku in sorted(needs_update_skus):
            if shown >= 10:
                break
            sv = shopify_variants[sku]
            cd = csv_pricing[sku]
            parts = []
            if sku in price_changes:
                parts.append(f"price {_fmt(sv['price'])} -> {_fmt(cd['price'])}")
            if sku in cost_changes:
                parts.append(f"cost {_fmt(sv['cost'])} -> {_fmt(cd['cost'])}")
            print(f"  {sku:25} {', '.join(parts)}")
            shown += 1
        if len(needs_update_skus) > 10:
            print(f"  ... and {len(needs_update_skus) - 10} more")
        print()

    if not needs_update_skus:
        print("Everything is up to date!")
        return 0

    if not args.fix:
        print(f"Run with --fix to update {len(needs_update_skus)} variants.")
        return 0

    # Apply updates
    products = list(by_product.items())
    if args.batch:
        products = products[:args.batch]
        print(f"Limiting to first {args.batch} products")
        print()

    total_ok = 0
    total_fail = 0

    print(f"Updating {sum(len(v) for _, v in products)} variants across {len(products)} products...")
    print()

    for i, (product_id, variants) in enumerate(products, 1):
        title = variants[0]["title"][:40]
        count, errors = update_variants_for_product(product_id, variants)

        if errors:
            print(f"  [{i}/{len(products)}] FAIL  {title}")
            for err in errors:
                print(f"           {err}")
            total_fail += len(variants)
        else:
            print(f"  [{i}/{len(products)}] OK    {title} ({count} variants)")
            total_ok += count

        time.sleep(0.5)

    print()
    print("=" * 70)
    print(f"Done! Updated: {total_ok}  Failed: {total_fail}")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
