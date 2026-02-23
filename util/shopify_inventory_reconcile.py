#!/usr/bin/env python3
"""
Reconcile Shopify inventory levels against Postgres cable counts.

Compares per-SKU counts of QC-passed cables in Postgres with Shopify's
available inventory. Also reports unsynced cables (passed QC but Shopify
wasn't incremented, e.g. due to network failure).

Usage:
    python util/shopify_inventory_reconcile.py            # Report only
    python util/shopify_inventory_reconcile.py --fix       # Re-sync unsynced cables
    python util/shopify_inventory_reconcile.py --unsynced  # Show only unsynced cables
"""

import sys
import argparse
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from greenlight.db import pg_pool, get_unsynced_passed_cables, mark_cable_shopify_synced, get_audio_cable
from greenlight.shopify_client import get_all_product_skus, increment_inventory_for_sku, ensure_special_baby_shopify_product


def get_postgres_passed_counts():
    """Get count of QC-passed cables per SKU from Postgres.

    For MISC cables with a special_baby_type, groups by the type's shopify_sku
    (e.g. SC-MISC-42) instead of the generic base SKU (SC-MISC).

    Returns:
        dict mapping SKU -> count of passed cables
    """
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COALESCE(sbt.shopify_sku, ac.sku) as effective_sku, COUNT(*)
                FROM audio_cables ac
                LEFT JOIN special_baby_types sbt ON ac.special_baby_type_id = sbt.id
                WHERE ac.test_passed = TRUE
                GROUP BY effective_sku
                ORDER BY effective_sku
            """)
            return {row[0]: row[1] for row in cur.fetchall()}
    finally:
        pg_pool.putconn(conn)


def print_reconciliation_report():
    """Print a comparison of Postgres passed counts vs Shopify inventory."""
    print("Fetching Postgres cable counts...")
    pg_counts = get_postgres_passed_counts()

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
            print(f"  {sku:<20} {count:>5} passed")

    if shopify_only:
        print(f"\nShopify only ({len(shopify_only)} SKUs) — no passed cables in Postgres:")
        for sku, qty in shopify_only:
            print(f"  {sku:<20} {qty:>5} in Shopify")

    if not mismatches and not pg_only:
        print("\nAll SKUs are in sync!")

    print()


def print_unsynced_report():
    """Print cables that passed QC but weren't synced to Shopify."""
    unsynced = get_unsynced_passed_cables()

    if not unsynced:
        print("No unsynced cables found. All passed cables are synced to Shopify.")
        return

    print(f"\nUnsynced cables ({len(unsynced)} total):")
    print(f"  {'Serial':<12} {'SKU':<20}")
    print(f"  {'-'*32}")

    # Group by SKU for summary
    sku_counts = {}
    for cable in unsynced:
        print(f"  {cable['serial_number']:<12} {cable['sku']:<20}")
        sku_counts[cable['sku']] = sku_counts.get(cable['sku'], 0) + 1

    print(f"\n  Summary by SKU:")
    for sku, count in sorted(sku_counts.items()):
        print(f"    {sku:<20} {count:>5} unsynced")
    print()


def fix_unsynced():
    """Re-sync unsynced cables by incrementing Shopify inventory."""
    unsynced = get_unsynced_passed_cables()

    if not unsynced:
        print("No unsynced cables to fix.")
        return

    print(f"Found {len(unsynced)} unsynced cables. Syncing to Shopify...")

    success_count = 0
    fail_count = 0

    for cable in unsynced:
        serial = cable['serial_number']
        sku = cable['sku']
        is_misc = sku.endswith('-MISC')

        if is_misc:
            cable_record = get_audio_cable(serial)
            if not cable_record:
                fail_count += 1
                print(f"  {serial} ({sku}): FAILED - cable record not found")
                continue
            success, err = ensure_special_baby_shopify_product(cable_record)
        else:
            success, err = increment_inventory_for_sku(sku)

        if success:
            mark_cable_shopify_synced(serial)
            success_count += 1
            print(f"  {serial} ({sku}): synced")
        else:
            fail_count += 1
            print(f"  {serial} ({sku}): FAILED - {err}")

    print(f"\nDone: {success_count} synced, {fail_count} failed")


def main():
    parser = argparse.ArgumentParser(
        description="Reconcile Shopify inventory with Postgres cable counts"
    )
    parser.add_argument(
        "--fix", action="store_true",
        help="Re-sync unsynced cables (increment Shopify for each)"
    )
    parser.add_argument(
        "--unsynced", action="store_true",
        help="Show only unsynced cables (passed QC, not synced to Shopify)"
    )
    args = parser.parse_args()

    if args.fix:
        fix_unsynced()
    elif args.unsynced:
        print_unsynced_report()
    else:
        print_reconciliation_report()
        print_unsynced_report()


if __name__ == "__main__":
    main()
