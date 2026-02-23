#!/usr/bin/env python3
"""
Sync product pricing, cost, and weight from YAML definitions to Shopify.

Reads YAML product line files (source of truth) and compares price, cost,
and weight against Shopify product variants. Reports differences and
optionally updates Shopify to match.

Usage:
    python util/shopify_price_sync.py           # Preview differences
    python util/shopify_price_sync.py --fix     # Update Shopify to match YAML
"""

import sys
import json
import argparse
from pathlib import Path

# Add util/ and project root to path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from sync_skus import (
    load_product_lines,
    load_patterns,
    get_patterns_for_fabric_type,
    generate_sku_code,
)
import shopify
from greenlight.shopify_client import get_shopify_session, close_shopify_session, SPECIAL_BABY_PRICE
from greenlight.db import pg_pool

WEIGHT_UNIT = "OUNCES"

# Map base_sku prefix to YAML sku_prefix
_PREFIX_MAP = {
    "SC": "SC",
    "TC": "TC",
    "SV": "SV",
    "TV": "TV",
}


def build_yaml_sku_map(product_lines_dir):
    """Build SKU -> {price, cost, weight} from YAML product line files."""
    patterns_file = product_lines_dir / 'patterns.yaml'
    patterns = load_patterns(patterns_file)
    product_lines = load_product_lines(product_lines_dir)

    sku_map = {}
    for pl in product_lines:
        prefix = pl['sku_prefix']
        include_color = pl.get('include_color_in_sku', True)
        matching_patterns = get_patterns_for_fabric_type(patterns, pl['braid_material'])
        connectors = pl.get('connectors', [])

        pricing = pl.get('pricing', {})
        cost_data = pl.get('cost', {})
        weight_data = pl.get('weight', {})

        for length in pl['lengths']:
            price = pricing.get(length)
            weight = weight_data.get(length)

            for pattern in matching_patterns:
                for connector in connectors:
                    sku = generate_sku_code(prefix, length, pattern['code'],
                                           connector['code'], include_color)

                    # Cost may have R suffix for right-angle connectors
                    is_right_angle = connector['code'] == '-R'
                    cost_key = f"{int(length)}R" if is_right_angle else length
                    cost = cost_data.get(cost_key)

                    sku_map[sku] = {
                        'price': float(price) if price is not None else None,
                        'cost': float(cost) if cost is not None else None,
                        'weight': float(weight) if weight is not None else None,
                    }

    return sku_map


def _interpolate(lengths_map, target_length):
    """Interpolate a value from a length-keyed map for a non-standard length.

    Finds the two nearest standard lengths and linearly interpolates.
    Extrapolates if target is outside the range.
    """
    if not lengths_map:
        return None

    # Sort by numeric length key
    points = sorted((float(k), float(v)) for k, v in lengths_map.items()
                    if not isinstance(k, str) or not k.endswith('R'))

    if not points:
        return None

    target = float(target_length)

    # Exact match
    for l, v in points:
        if abs(l - target) < 0.01:
            return v

    # Find bracketing points
    below = [(l, v) for l, v in points if l < target]
    above = [(l, v) for l, v in points if l > target]

    if below and above:
        l1, v1 = below[-1]
        l2, v2 = above[0]
    elif below:
        # Extrapolate above using last two points
        if len(points) >= 2:
            l1, v1 = points[-2]
            l2, v2 = points[-1]
        else:
            return points[-1][1]
    else:
        # Extrapolate below using first two points
        if len(points) >= 2:
            l1, v1 = points[0]
            l2, v2 = points[1]
        else:
            return points[0][1]

    rate = (v2 - v1) / (l2 - l1)
    return round(v1 + rate * (target - l1), 2)


def build_special_baby_sku_map(product_lines_dir):
    """Build shopify_sku -> {price, cost, weight} for special baby types.

    Reads special_baby_types from DB and interpolates cost/weight
    from the matching product line YAML based on length.
    """
    product_lines = load_product_lines(product_lines_dir)

    # Index product lines by sku_prefix
    pl_by_prefix = {}
    for pl in product_lines:
        pl_by_prefix[pl['sku_prefix']] = pl

    # Get all special baby types from DB
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT shopify_sku, base_sku, length
                FROM special_baby_types
                WHERE shopify_sku IS NOT NULL
            """)
            rows = cur.fetchall()
    finally:
        pg_pool.putconn(conn)

    sku_map = {}
    for shopify_sku, base_sku, length in rows:
        if not length:
            continue

        # Derive prefix from base_sku (e.g. "SC-MISC" -> "SC")
        prefix = base_sku.split('-')[0]
        pl = pl_by_prefix.get(prefix)
        if not pl:
            continue

        cost = _interpolate(pl.get('cost', {}), length)
        weight = _interpolate(pl.get('weight', {}), length)

        sku_map[shopify_sku] = {
            'price': float(SPECIAL_BABY_PRICE),
            'cost': cost,
            'weight': weight,
        }

    return sku_map


def fetch_shopify_variants():
    """Fetch all Shopify variants with price, cost, and weight.

    Returns dict mapping SKU -> variant details.
    """
    try:
        session = get_shopify_session()

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
                                    price
                                    inventoryItem {
                                        id
                                        unitCost {
                                            amount
                                        }
                                        measurement {
                                            weight {
                                                value
                                                unit
                                            }
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
                    if not sku:
                        continue

                    inv = v.get("inventoryItem") or {}
                    unit_cost = inv.get("unitCost") or {}
                    measurement = inv.get("measurement") or {}
                    weight_data = measurement.get("weight") or {}

                    cost_amt = unit_cost.get("amount")
                    weight_val = weight_data.get("value")

                    variants[sku] = {
                        'variant_id': v["id"],
                        'product_id': product_id,
                        'inventory_item_id': inv.get("id"),
                        'price': float(v.get("price") or 0),
                        'cost': float(cost_amt) if cost_amt else None,
                        'weight': float(weight_val) if weight_val else None,
                        'weight_unit': weight_data.get("unit"),
                    }

            has_next_page = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")

        return variants

    except Exception as e:
        print(f"   Error fetching Shopify variants: {e}")
        return {}
    finally:
        close_shopify_session()


def _convert_weight_to_ounces(value, unit):
    """Convert a Shopify weight value to ounces for comparison."""
    if value is None:
        return None
    conversions = {
        "OUNCES": 1.0,
        "POUNDS": 16.0,
        "GRAMS": 0.035274,
        "KILOGRAMS": 35.274,
    }
    factor = conversions.get(unit, 1.0)
    return round(value * factor, 2)


def _floats_differ(a, b, tol=0.01):
    """Compare two floats (either may be None)."""
    if a is None and b is None:
        return False
    if a is None or b is None:
        return True
    return abs(a - b) > tol


def find_differences(yaml_map, shopify_map):
    """Compare YAML values against Shopify and return list of differences."""
    diffs = []

    for sku, yaml_vals in sorted(yaml_map.items()):
        if sku not in shopify_map:
            continue  # SKU not in Shopify — shopify_sku_sync.py handles that

        shopify_vals = shopify_map[sku]

        price_diff = False
        cost_diff = False
        weight_diff = False

        # Compare price
        if yaml_vals['price'] is not None:
            price_diff = _floats_differ(yaml_vals['price'], shopify_vals['price'])

        # Compare cost
        if yaml_vals['cost'] is not None:
            cost_diff = _floats_differ(yaml_vals['cost'], shopify_vals['cost'])

        # Compare weight (convert Shopify weight to ounces)
        if yaml_vals['weight'] is not None:
            shopify_weight_oz = _convert_weight_to_ounces(
                shopify_vals['weight'], shopify_vals.get('weight_unit'))
            weight_diff = _floats_differ(yaml_vals['weight'], shopify_weight_oz)

        if price_diff or cost_diff or weight_diff:
            shopify_weight_oz = _convert_weight_to_ounces(
                shopify_vals['weight'], shopify_vals.get('weight_unit'))
            diffs.append({
                'sku': sku,
                'variant_id': shopify_vals['variant_id'],
                'product_id': shopify_vals['product_id'],
                'inventory_item_id': shopify_vals['inventory_item_id'],
                'price_diff': price_diff,
                'cost_diff': cost_diff,
                'weight_diff': weight_diff,
                'yaml_price': yaml_vals['price'],
                'yaml_cost': yaml_vals['cost'],
                'yaml_weight': yaml_vals['weight'],
                'shopify_price': shopify_vals['price'],
                'shopify_cost': shopify_vals['cost'],
                'shopify_weight': shopify_weight_oz,
            })

    return diffs


def update_variant(product_id, variant_id, price=None, cost=None, weight=None):
    """Update a Shopify variant's price, cost, and/or weight in one call.

    Uses productVariantsBulkUpdate which accepts price on the variant
    and cost/weight via the nested inventoryItem input.
    """
    try:
        session = get_shopify_session()
        mutation = """
        mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
            productVariantsBulkUpdate(productId: $productId, variants: $variants) {
                productVariants { id }
                userErrors { field message }
            }
        }
        """
        variant_input = {"id": variant_id}

        if price is not None:
            variant_input["price"] = f"{price:.2f}"

        inv_item = {}
        if cost is not None:
            inv_item["cost"] = cost
        if weight is not None:
            inv_item["measurement"] = {
                "weight": {
                    "value": weight,
                    "unit": WEIGHT_UNIT,
                }
            }
        if inv_item:
            variant_input["inventoryItem"] = inv_item

        variables = {
            "productId": product_id,
            "variants": [variant_input],
        }
        result = shopify.GraphQL().execute(mutation, variables=variables)
        data = json.loads(result)

        if "errors" in data:
            return False, str(data["errors"])

        user_errors = (data.get("data", {})
                       .get("productVariantsBulkUpdate", {})
                       .get("userErrors", []))
        if user_errors:
            return False, "; ".join(e["message"] for e in user_errors)

        return True, None
    except Exception as e:
        return False, str(e)
    finally:
        close_shopify_session()


def main():
    parser = argparse.ArgumentParser(
        description='Sync pricing, cost, and weight from YAML to Shopify'
    )
    parser.add_argument('--fix', action='store_true',
                        help='Update Shopify to match YAML values')
    args = parser.parse_args()

    product_lines_dir = Path(__file__).parent / 'product_lines'

    print("Shopify Price/Cost/Weight Sync")
    print("=" * 70)
    print()

    # Build YAML SKU map
    print("Loading YAML product definitions...")
    yaml_map = build_yaml_sku_map(product_lines_dir)
    print(f"   {len(yaml_map)} standard SKUs from YAML")

    # Add special baby types (cost/weight interpolated from YAML)
    special_map = build_special_baby_sku_map(product_lines_dir)
    yaml_map.update(special_map)
    print(f"   {len(special_map)} special baby SKUs from DB")
    print(f"   {len(yaml_map)} total SKUs")
    print()

    # Fetch Shopify data
    print("Fetching Shopify variants...")
    shopify_map = fetch_shopify_variants()
    print(f"   {len(shopify_map)} variants from Shopify")
    print()

    # Find differences
    diffs = find_differences(yaml_map, shopify_map)

    # Count by type
    price_diffs = [d for d in diffs if d['price_diff']]
    cost_diffs = [d for d in diffs if d['cost_diff']]
    weight_diffs = [d for d in diffs if d['weight_diff']]

    yaml_only = set(yaml_map.keys()) - set(shopify_map.keys())
    matched = set(yaml_map.keys()) & set(shopify_map.keys())

    print("=" * 70)
    print(f"Summary:")
    print(f"   YAML SKUs:       {len(yaml_map)}")
    print(f"   Shopify SKUs:    {len(shopify_map)}")
    print(f"   Matched:         {len(matched)}")
    print(f"   Not in Shopify:  {len(yaml_only)}")
    print(f"   Price diffs:     {len(price_diffs)}")
    print(f"   Cost diffs:      {len(cost_diffs)}")
    print(f"   Weight diffs:    {len(weight_diffs)}")
    print("=" * 70)
    print()

    if not diffs:
        print("All matched SKUs are up to date!")
        return 0

    # Show differences
    def _fmt(val, prefix="$"):
        if val is None:
            return "not set"
        if prefix:
            return f"{prefix}{val:.2f}"
        return f"{val:.2f}"

    if price_diffs:
        print(f"Price differences ({len(price_diffs)}):")
        for d in price_diffs:
            print(f"   {d['sku']:20}  YAML {_fmt(d['yaml_price'])}  Shopify {_fmt(d['shopify_price'])}")
        print()

    if cost_diffs:
        print(f"Cost differences ({len(cost_diffs)}):")
        for d in cost_diffs:
            print(f"   {d['sku']:20}  YAML {_fmt(d['yaml_cost'])}  Shopify {_fmt(d['shopify_cost'])}")
        print()

    if weight_diffs:
        print(f"Weight differences ({len(weight_diffs)}):")
        for d in weight_diffs:
            print(f"   {d['sku']:20}  YAML {_fmt(d['yaml_weight'], '')} oz  Shopify {_fmt(d['shopify_weight'], '')} oz")
        print()

    if not args.fix:
        print(f"Run with --fix to update Shopify.")
        print(f"   Command: python util/shopify_price_sync.py --fix")
        return 0

    # Apply fixes
    print("Updating Shopify...")
    print()

    fixed = 0
    failed = 0

    for d in diffs:
        sku = d['sku']
        price_val = d['yaml_price'] if d['price_diff'] else None
        cost_val = d['yaml_cost'] if d['cost_diff'] else None
        weight_val = d['yaml_weight'] if d['weight_diff'] else None

        ok, err = update_variant(
            d['product_id'], d['variant_id'],
            price=price_val, cost=cost_val, weight=weight_val)

        if ok:
            changes = []
            if price_val is not None:
                changes.append(f"price=${price_val:.2f}")
            if cost_val is not None:
                changes.append(f"cost=${cost_val:.2f}")
            if weight_val is not None:
                changes.append(f"weight={weight_val:.2f}oz")
            print(f"   OK   {sku:20}  {', '.join(changes)}")
            fixed += 1
        else:
            print(f"   FAIL {sku}: {err}")
            failed += 1

    print()
    print("=" * 70)
    print(f"Done! Updated: {fixed}  Failed: {failed}")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
