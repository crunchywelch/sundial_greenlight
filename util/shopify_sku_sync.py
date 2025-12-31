#!/usr/bin/env python3
"""
Compare cable SKUs between PostgreSQL database and Shopify products.

This script:
1. Fetches all product SKUs from Shopify
2. Fetches all cable SKUs from the database
3. Compares and reports:
   - SKUs in database but NOT in Shopify (need to add to store)
   - SKUs in Shopify but NOT in database (orphaned/unknown products)
   - SKUs in both (with inventory comparison)

Usage:
    python util/shopify_sku_sync.py              # Full comparison report
    python util/shopify_sku_sync.py --missing    # Show only missing SKUs
    python util/shopify_sku_sync.py --orphaned   # Show only orphaned SKUs
"""

import sys
import argparse
from pathlib import Path
from typing import Dict, Set

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from greenlight.db import pg_pool
from greenlight.shopify_client import get_all_product_skus


def get_database_skus() -> Dict[str, Dict[str, str]]:
    """
    Get all SKUs from the database.

    Returns:
        Dictionary mapping SKU -> SKU details
        {
            "SC-1BG": {
                "series": "Studio Classic",
                "description": "...",
                "core_cable": "Canare GS-6",
                ...
            }
        }
    """
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT sku, series, core_cable, braid_material,
                       color_pattern, length, connector_type, description
                FROM cable_skus
                ORDER BY sku
            """)

            sku_map = {}
            for row in cur.fetchall():
                sku_map[row[0]] = {
                    'sku': row[0],
                    'series': row[1],
                    'core_cable': row[2],
                    'braid_material': row[3],
                    'color_pattern': row[4],
                    'length': row[5],
                    'connector_type': row[6],
                    'description': row[7]
                }

            return sku_map
    except Exception as e:
        print(f"❌ Error fetching database SKUs: {e}")
        return {}
    finally:
        pg_pool.putconn(conn)


def main():
    parser = argparse.ArgumentParser(
        description='Compare SKUs between database and Shopify'
    )
    parser.add_argument('--missing', action='store_true',
                        help='Show only SKUs in database but not in Shopify')
    parser.add_argument('--orphaned', action='store_true',
                        help='Show only SKUs in Shopify but not in database')
    parser.add_argument('--matched', action='store_true',
                        help='Show only SKUs that exist in both systems')
    args = parser.parse_args()

    print("🔄 Shopify SKU Sync Comparison")
    print("=" * 80)
    print()

    # Fetch data from both systems
    print("📚 Fetching SKUs from database...")
    db_skus = get_database_skus()
    print(f"✅ Found {len(db_skus)} SKUs in database")
    print()

    print("🛒 Fetching products from Shopify...")
    shopify_skus = get_all_product_skus()
    print(f"✅ Found {len(shopify_skus)} SKUs in Shopify")
    print()

    # Compare SKU sets
    db_sku_codes = set(db_skus.keys())
    shopify_sku_codes = set(shopify_skus.keys())

    missing_in_shopify = db_sku_codes - shopify_sku_codes
    orphaned_in_shopify = shopify_sku_codes - db_sku_codes
    matched_skus = db_sku_codes & shopify_sku_codes

    # Summary
    print("=" * 80)
    print(f"📊 Summary:")
    print(f"   Database SKUs:           {len(db_skus)}")
    print(f"   Shopify SKUs:            {len(shopify_skus)}")
    print(f"   Matched (in both):       {len(matched_skus)}")
    print(f"   Missing from Shopify:    {len(missing_in_shopify)}")
    print(f"   Orphaned in Shopify:     {len(orphaned_in_shopify)}")
    print("=" * 80)
    print()

    # Show missing SKUs (in database but not in Shopify)
    if not args.orphaned and not args.matched:
        if missing_in_shopify:
            print(f"⚠️  SKUs in DATABASE but NOT in SHOPIFY ({len(missing_in_shopify)}):")
            print("   These SKUs should be added as products in Shopify")
            print()

            # Group by series for better readability
            by_series = {}
            for sku_code in missing_in_shopify:
                sku_data = db_skus[sku_code]
                series = sku_data['series']
                if series not in by_series:
                    by_series[series] = []
                by_series[series].append(sku_data)

            for series in sorted(by_series.keys()):
                skus = by_series[series]
                print(f"   {series} ({len(skus)} SKUs):")
                for sku_data in sorted(skus, key=lambda x: x['sku'])[:20]:
                    length = sku_data['length']
                    color = sku_data['color_pattern']
                    connector = sku_data['connector_type']
                    print(f"      {sku_data['sku']:20} | {length:>4}ft | {color:15} | {connector}")

                if len(skus) > 20:
                    print(f"      ... and {len(skus) - 20} more")
                print()
        else:
            print("✅ All database SKUs exist in Shopify!")
            print()

    # Show orphaned SKUs (in Shopify but not in database)
    if not args.missing and not args.matched:
        if orphaned_in_shopify:
            print(f"⚠️  SKUs in SHOPIFY but NOT in DATABASE ({len(orphaned_in_shopify)}):")
            print("   These products exist in your store but aren't in your database")
            print()

            for sku_code in sorted(orphaned_in_shopify)[:30]:
                shopify_data = shopify_skus[sku_code]
                product_title = shopify_data['product_title']
                variant_title = shopify_data.get('variant_title', '')
                price = shopify_data.get('price', '0')
                inventory = shopify_data.get('inventory_quantity', 0)
                status = shopify_data.get('status', 'UNKNOWN')

                print(f"   {sku_code:20} | {status:8} | ${price:>6} | Qty: {inventory:>3} | {product_title}")

            if len(orphaned_in_shopify) > 30:
                print(f"   ... and {len(orphaned_in_shopify) - 30} more")
            print()
        else:
            print("✅ No orphaned SKUs in Shopify!")
            print()

    # Show matched SKUs
    if not args.missing and not args.orphaned:
        if matched_skus:
            print(f"✅ MATCHED SKUs (in both systems) - {len(matched_skus)} SKUs:")
            print()

            # Show inventory summary by series
            by_series = {}
            total_inventory = 0

            for sku_code in matched_skus:
                db_data = db_skus[sku_code]
                shopify_data = shopify_skus[sku_code]
                series = db_data['series']
                inventory = shopify_data.get('inventory_quantity', 0)

                if series not in by_series:
                    by_series[series] = {
                        'count': 0,
                        'inventory': 0,
                        'skus': []
                    }

                by_series[series]['count'] += 1
                by_series[series]['inventory'] += inventory
                by_series[series]['skus'].append({
                    'sku': sku_code,
                    'inventory': inventory,
                    'price': shopify_data.get('price', '0'),
                    'status': shopify_data.get('status', 'UNKNOWN')
                })
                total_inventory += inventory

            print(f"   Inventory Summary by Series:")
            print()
            for series in sorted(by_series.keys()):
                data = by_series[series]
                print(f"   {series:25} | {data['count']:3} SKUs | Total Inventory: {data['inventory']:4}")

            print()
            print(f"   Total Inventory Across All Matched SKUs: {total_inventory}")
            print()

            # Show some examples
            print(f"   Sample matched SKUs (showing first 15):")
            print()
            shown = 0
            for sku_code in sorted(matched_skus):
                if shown >= 15:
                    break

                db_data = db_skus[sku_code]
                shopify_data = shopify_skus[sku_code]
                series = db_data['series']
                inventory = shopify_data.get('inventory_quantity', 0)
                price = shopify_data.get('price', '0')
                status = shopify_data.get('status', 'UNKNOWN')

                print(f"      {sku_code:20} | {series:20} | ${price:>6} | Qty: {inventory:>3} | {status}")
                shown += 1

            if len(matched_skus) > 15:
                print(f"      ... and {len(matched_skus) - 15} more")
            print()
        else:
            print("⚠️  No matched SKUs found!")
            print()

    print()
    print("=" * 80)
    print("ℹ️  Next Steps:")
    if missing_in_shopify:
        print(f"   • Add {len(missing_in_shopify)} missing SKUs to Shopify products")
    if orphaned_in_shopify:
        print(f"   • Review {len(orphaned_in_shopify)} orphaned Shopify SKUs")
        print(f"     - Update SKUs in Shopify to match database, OR")
        print(f"     - Add these SKUs to database if they're valid products")
    if not missing_in_shopify and not orphaned_in_shopify:
        print("   ✅ All SKUs are synchronized!")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    sys.exit(main())
