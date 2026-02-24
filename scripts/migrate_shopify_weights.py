#!/usr/bin/env python3
"""One-time migration: set weight, metafields, and category on special baby Shopify products.

Reads cable attributes from Postgres (special_baby_types joined to cable_skus),
calculates weight from materials.yaml, and updates each special baby product:
  - Weight via inventoryItemUpdate
  - Metafields (length, series, cable_type) via metafieldsSet
  - Product category ("Audio & Video Cables") via productUpdate

Usage:
    source dev_env.sh
    python scripts/migrate_shopify_weights.py          # dry-run (default)
    python scripts/migrate_shopify_weights.py --apply   # actually update Shopify
"""

import sys
import os
import json
import argparse

# Add project root to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import shopify
from greenlight.shopify_client import (
    get_shopify_session, close_shopify_session,
    get_all_product_skus,
    _calculate_cable_weight_oz, _load_materials,
    _derive_cable_type, _derive_series_metafield, _resolve_cable_attrs,
    AUDIO_VIDEO_CABLES_CATEGORY_ID,
)
from greenlight.db import pg_pool


def get_special_baby_attrs_by_sku():
    """Build a map of special baby shopify_sku -> {connector_type, core_cable, length, series}."""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT sbt.shopify_sku, cs.connector_type, cs.core_cable,
                       sbt.length, cs.series
                FROM special_baby_types sbt
                JOIN cable_skus cs ON sbt.base_sku = cs.sku
                WHERE sbt.shopify_sku IS NOT NULL
            """)
            attrs = {}
            for shopify_sku, connector_type, core_cable, length, series in cur.fetchall():
                attrs[shopify_sku] = {
                    "connector_type": connector_type,
                    "core_cable": core_cable,
                    "length": float(length) if length else None,
                    "series": series,
                }
            return attrs
    finally:
        pg_pool.putconn(conn)


def update_inventory_item_weight(inventory_item_id, weight_oz):
    """Update weight on a Shopify inventory item."""
    session = get_shopify_session()
    try:
        mutation = """
        mutation inventoryItemUpdate($id: ID!, $input: InventoryItemInput!) {
            inventoryItemUpdate(id: $id, input: $input) {
                inventoryItem {
                    id
                    measurement {
                        weight { value unit }
                    }
                }
                userErrors { field message }
            }
        }
        """
        variables = {
            "id": inventory_item_id,
            "input": {
                "measurement": {
                    "weight": {"value": weight_oz, "unit": "OUNCES"}
                }
            },
        }
        result = shopify.GraphQL().execute(mutation, variables=variables)
        data = json.loads(result)

        if "errors" in data:
            return False, str(data["errors"])

        user_errors = data.get("data", {}).get("inventoryItemUpdate", {}).get("userErrors", [])
        if user_errors:
            return False, "; ".join(e["message"] for e in user_errors)

        return True, None
    finally:
        close_shopify_session()


def set_product_category(product_id, category_id):
    """Set product category via productUpdate."""
    session = get_shopify_session()
    try:
        mutation = """
        mutation productUpdate($input: ProductInput!) {
            productUpdate(input: $input) {
                product { id category { id name } }
                userErrors { field message }
            }
        }
        """
        variables = {
            "input": {
                "id": product_id,
                "category": category_id,
            }
        }
        result = shopify.GraphQL().execute(mutation, variables=variables)
        data = json.loads(result)

        if "errors" in data:
            return False, str(data["errors"])

        user_errors = data.get("data", {}).get("productUpdate", {}).get("userErrors", [])
        if user_errors:
            return False, "; ".join(e["message"] for e in user_errors)

        return True, None
    finally:
        close_shopify_session()


def set_metafields_batch(metafield_batch):
    """Set up to 25 metafields in a single metafieldsSet call.

    Returns (success_count, error_messages).
    """
    session = get_shopify_session()
    try:
        mutation = """
        mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
            metafieldsSet(metafields: $metafields) {
                metafields { id namespace key }
                userErrors { field message }
            }
        }
        """
        result = shopify.GraphQL().execute(mutation, variables={"metafields": metafield_batch})
        data = json.loads(result)

        if "errors" in data:
            return 0, str(data["errors"])

        user_errors = data.get("data", {}).get("metafieldsSet", {}).get("userErrors", [])
        if user_errors:
            return 0, "; ".join(e["message"] for e in user_errors)

        set_fields = data.get("data", {}).get("metafieldsSet", {}).get("metafields", [])
        return len(set_fields), None
    finally:
        close_shopify_session()


def build_metafields_for_product(product_id, length, series, connector_type):
    """Build the 3 metafield dicts for a product."""
    cable_type = _derive_cable_type(connector_type)
    series_value = _derive_series_metafield(series)
    length_int = int(length) if length == int(length) else length
    length_value = f"{length_int} ft"

    return [
        {
            "ownerId": product_id,
            "namespace": "custom",
            "key": "cable_length",
            "value": length_value,
            "type": "single_line_text_field",
        },
        {
            "ownerId": product_id,
            "namespace": "custom",
            "key": "series",
            "value": series_value,
            "type": "single_line_text_field",
        },
        {
            "ownerId": product_id,
            "namespace": "custom",
            "key": "cable_type",
            "value": cable_type,
            "type": "single_line_text_field",
        },
    ]


def main():
    parser = argparse.ArgumentParser(description="Migrate Shopify product weights and metafields")
    parser.add_argument("--apply", action="store_true", help="Actually update Shopify (default is dry-run)")
    args = parser.parse_args()

    # Verify materials.yaml loads
    materials = _load_materials()
    if not materials.get("cable_per_foot") or not materials.get("connectors"):
        print("ERROR: materials.yaml missing or incomplete")
        sys.exit(1)
    print(f"Materials loaded: {materials}")

    # Get cable attributes from Postgres
    print("\nFetching special baby attributes from Postgres...")
    cable_attrs = get_special_baby_attrs_by_sku()
    print(f"  Found {len(cable_attrs)} special baby SKUs in database")

    # Get all Shopify products
    print("\nFetching all Shopify products...")
    shopify_skus = get_all_product_skus()
    print(f"  Found {len(shopify_skus)} SKUs in Shopify")

    # Match and calculate
    weight_updated = 0
    skipped = 0
    weight_errors = 0
    category_updated = 0
    category_errors = 0
    no_match = []
    pending_metafields = []  # accumulate for batching
    metafield_products = 0
    metafield_errors = 0

    for sku, product_info in sorted(shopify_skus.items()):
        attrs = cable_attrs.get(sku)
        if not attrs:
            no_match.append(sku)
            skipped += 1
            continue

        length = attrs["length"]
        series = attrs["series"]
        connector_type, core_cable = _resolve_cable_attrs(
            attrs["connector_type"], attrs["core_cable"], series
        )

        if not all([length, connector_type, core_cable]):
            print(f"  SKIP {sku}: missing attrs (length={length}, connector={connector_type}, cable={core_cable})")
            skipped += 1
            continue

        weight_oz = _calculate_cable_weight_oz(length, connector_type, core_cable)
        if weight_oz is None:
            print(f"  SKIP {sku}: weight calc returned None (connector={connector_type}, cable={core_cable})")
            skipped += 1
            continue

        inv_item_id = product_info.get("inventory_item_id")
        product_id = product_info.get("product_id")
        title = product_info.get("product_title", "")
        status = product_info.get("status", "")
        cable_type = _derive_cable_type(connector_type)
        length_display = int(length) if length == int(length) else length

        if args.apply:
            # Update weight
            ok, err = update_inventory_item_weight(inv_item_id, weight_oz)
            if ok:
                print(f"  OK   {sku:20s}  {weight_oz:5.1f} oz  {series:22s} {cable_type:12s} {length_display}ft  [{status}] {title}")
                weight_updated += 1
            else:
                print(f"  ERR  {sku:20s}  weight: {err}")
                weight_errors += 1

            # Set product category
            if product_id:
                ok, err = set_product_category(product_id, AUDIO_VIDEO_CABLES_CATEGORY_ID)
                if ok:
                    category_updated += 1
                else:
                    print(f"  ERR  {sku:20s}  category: {err}")
                    category_errors += 1

            # Queue metafields
            if product_id and series:
                pending_metafields.extend(
                    build_metafields_for_product(product_id, length, series, connector_type)
                )
                metafield_products += 1

                # Flush batch at 24 (8 products × 3 metafields = 24, under the 25 limit)
                if len(pending_metafields) >= 24:
                    count, err = set_metafields_batch(pending_metafields)
                    if err:
                        print(f"  ERR  metafields batch: {err}")
                        metafield_errors += 1
                    pending_metafields = []
        else:
            print(f"  DRY  {sku:20s}  {weight_oz:5.1f} oz  {series:22s} {cable_type:12s} {length_display}ft  [{status}] {title}")
            weight_updated += 1

    # Flush remaining metafields
    if args.apply and pending_metafields:
        count, err = set_metafields_batch(pending_metafields)
        if err:
            print(f"  ERR  metafields batch: {err}")
            metafield_errors += 1

    # Summary
    print(f"\n{'=' * 60}")
    mode = "APPLIED" if args.apply else "DRY RUN"
    print(f"  {mode}:")
    print(f"    Weight:     {weight_updated} updated, {weight_errors} errors")
    if args.apply:
        print(f"    Category:   {category_updated} updated, {category_errors} errors")
        print(f"    Metafields: {metafield_products} products, {metafield_errors} batch errors")
    print(f"    Skipped:    {skipped}")

    if no_match:
        print(f"\n  No DB match for {len(no_match)} Shopify SKUs:")
        for sku in no_match:
            title = shopify_skus[sku].get("product_title", "")
            print(f"    {sku:20s}  {title}")

    if not args.apply and weight_updated > 0:
        print(f"\n  Re-run with --apply to update Shopify.")


if __name__ == "__main__":
    main()
