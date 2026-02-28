#!/usr/bin/env python3
"""
Reconcile Shopify inventory levels against Postgres cable counts.

Compares per-SKU counts of available cables (passed QC, not assigned to a
customer) in Postgres with Shopify's available inventory.  The --fix flag
sets Shopify to match Postgres for any mismatched SKUs.

Usage:
    python util/audio/shopify_inventory_reconcile.py            # Report only
    python util/audio/shopify_inventory_reconcile.py --fix       # Fix mismatches
"""

import sys
import argparse
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from greenlight.db import pg_pool
from greenlight.shopify_client import get_all_product_skus, set_inventory_for_sku, ensure_special_baby_shopify_product
from greenlight.db import get_audio_cable


def get_postgres_available_counts():
    """Get count of available (passed + unassigned) cables per effective SKU.

    For MISC cables with a special_baby_type, groups by the type's shopify_sku
    (e.g. SC-MISC-42) instead of the generic base SKU (SC-MISC).

    Returns:
        dict mapping SKU -> count of available cables
    """
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COALESCE(sbt.shopify_sku, ac.sku) as effective_sku, COUNT(*)
                FROM audio_cables ac
                LEFT JOIN special_baby_types sbt ON ac.special_baby_type_id = sbt.id
                WHERE ac.test_passed = TRUE
                  AND (ac.shopify_gid IS NULL OR ac.shopify_gid = '')
                GROUP BY effective_sku
                ORDER BY effective_sku
            """)
            return {row[0]: row[1] for row in cur.fetchall()}
    finally:
        pg_pool.putconn(conn)


def print_reconciliation_report():
    """Print a comparison of Postgres available counts vs Shopify inventory."""
    print("Fetching Postgres available cable counts...")
    pg_counts = get_postgres_available_counts()

    print("Fetching Shopify inventory levels...")
    shopify_skus = get_all_product_skus()

    all_skus = sorted(set(pg_counts.keys()) | set(shopify_skus.keys()))

    if not all_skus:
        print("No SKUs found in either system.")
        return

    mismatches = []
    matches = []
    pg_only = []
    shopify_only = []

    for sku in all_skus:
        pg_count = pg_counts.get(sku, 0)
        shopify_info = shopify_skus.get(sku)
        shopify_qty = shopify_info["inventory_quantity"] if shopify_info else None

        if pg_count > 0 and shopify_qty is None:
            pg_only.append((sku, pg_count))
        elif pg_count == 0 and shopify_qty is not None:
            shopify_only.append((sku, shopify_qty))
        elif shopify_qty is not None and pg_count != shopify_qty:
            mismatches.append((sku, pg_count, shopify_qty))
        elif shopify_qty is not None:
            matches.append((sku, pg_count))

    # Print report
    print(f"\n{'='*60}")
    print("INVENTORY RECONCILIATION REPORT")
    print(f"{'='*60}")

    if matches:
        print(f"\nMatching ({len(matches)} SKUs):")
        for sku, count in matches:
            print(f"  {sku:<20} {count:>5}")

    if mismatches:
        print(f"\nMismatches ({len(mismatches)} SKUs):")
        print(f"  {'SKU':<20} {'Postgres':>10} {'Shopify':>10} {'Delta':>10}")
        print(f"  {'-'*50}")
        for sku, pg, sh in mismatches:
            delta = pg - sh
            sign = "+" if delta > 0 else ""
            print(f"  {sku:<20} {pg:>10} {sh:>10} {sign}{delta:>9}")

    if pg_only:
        print(f"\nPostgres only ({len(pg_only)} SKUs) — not in Shopify:")
        for sku, count in pg_only:
            print(f"  {sku:<20} {count:>5} available")

    if shopify_only:
        print(f"\nShopify only ({len(shopify_only)} SKUs) — no available cables in Postgres:")
        for sku, qty in shopify_only:
            print(f"  {sku:<20} {qty:>5} in Shopify")

    if not mismatches and not pg_only:
        print("\nAll SKUs are in sync!")

    print()
    return mismatches, pg_only


def fix_mismatches():
    """Set Shopify inventory to match Postgres for all mismatched SKUs."""
    print("Fetching Postgres available cable counts...")
    pg_counts = get_postgres_available_counts()

    print("Fetching Shopify inventory levels...")
    shopify_skus = get_all_product_skus()

    all_skus = sorted(set(pg_counts.keys()) | set(shopify_skus.keys()))

    fixes_needed = []
    for sku in all_skus:
        pg_count = pg_counts.get(sku, 0)
        shopify_info = shopify_skus.get(sku)
        shopify_qty = shopify_info["inventory_quantity"] if shopify_info else None

        if shopify_qty is not None and pg_count != shopify_qty:
            fixes_needed.append((sku, pg_count, shopify_qty))
        elif pg_count > 0 and shopify_qty is None:
            fixes_needed.append((sku, pg_count, None))

    if not fixes_needed:
        print("No mismatches to fix.")
        return

    print(f"\nFixing {len(fixes_needed)} mismatched SKUs...")
    success_count = 0
    fail_count = 0

    for sku, pg_count, shopify_qty in fixes_needed:
        old_str = str(shopify_qty) if shopify_qty is not None else "N/A"

        # For MISC SKUs not yet in Shopify, we need to create the product
        if shopify_qty is None and '-MISC-' in sku:
            # Find a cable with this special baby type to get the record
            conn = pg_pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT ac.serial_number
                        FROM audio_cables ac
                        LEFT JOIN special_baby_types sbt ON ac.special_baby_type_id = sbt.id
                        WHERE sbt.shopify_sku = %s AND ac.test_passed = TRUE
                        LIMIT 1
                    """, (sku,))
                    row = cur.fetchone()
            finally:
                pg_pool.putconn(conn)

            if row:
                cable_record = get_audio_cable(row[0])
                if cable_record:
                    success, err = ensure_special_baby_shopify_product(cable_record, quantity=pg_count)
                    if success:
                        success_count += 1
                        print(f"  {sku}: created product, set to {pg_count}")
                    else:
                        fail_count += 1
                        print(f"  {sku}: FAILED to create - {err}")
                    continue

            fail_count += 1
            print(f"  {sku}: FAILED - no cable record found for MISC SKU")
            continue

        # For existing Shopify products, just set the quantity
        success, err = set_inventory_for_sku(sku, pg_count)
        if success:
            success_count += 1
            print(f"  {sku}: {old_str} -> {pg_count}")
        else:
            fail_count += 1
            print(f"  {sku}: FAILED - {err}")

    print(f"\nDone: {success_count} fixed, {fail_count} failed")


def main():
    parser = argparse.ArgumentParser(
        description="Reconcile Shopify inventory with Postgres available cable counts"
    )
    parser.add_argument(
        "--fix", action="store_true",
        help="Set Shopify inventory to match Postgres for mismatched SKUs"
    )
    args = parser.parse_args()

    if args.fix:
        fix_mismatches()
    else:
        print_reconciliation_report()


if __name__ == "__main__":
    main()
