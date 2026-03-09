#!/usr/bin/env python3
"""
Nightly inventory valuation snapshot.

Refreshes product data from both Shopify stores (wire + audio), queries
PostgreSQL for available audio cable counts, computes inventory value for
each category, and stores the result in the daily_valuations table.

Designed to run as a cron job:
    0 2 * * * cd /home/welch/projects/sundial_greenlight && source dev_env.sh && python util/nightly_valuation.py

Usage:
    python util/nightly_valuation.py                # Run valuation for today
    python util/nightly_valuation.py --date 2026-03-01  # Override date
    python util/nightly_valuation.py --show         # Show recent valuations
"""

import argparse
import random
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from util.wire.sundial_wire_db import get_db, init_db, upsert_daily_valuation
from util.tax_assessment import load_excluded_skus

# Made-to-order product types — not real on-hand inventory
MADE_TO_ORDER_TYPES = {
    "Cord Set with 14g Pulley Cord",
    "Cord Set with 16-Gauge Twisted Pair Wire",
    "Cord Set with 18-Gauge Twisted Pair Wire",
    "Cord Set with 2-Conductor 18-Gauge Pulley Cord",
    "Cord Set with 20-Gauge Twisted Pair Wire",
    "Cord Set with 22-Gauge Twisted Pair Wire",
    "Cord Set with 3C 18g Pulley Cord",
    "Cord Set with Overbraid Wire",
    "Cord Set with Parallel Cord",
    "Pendant with 14-Gauge Pulley Cord",
    "Pendant with 16-Gauge Twisted Pair",
    "Pendant with 18-Gauge Twisted Pair",
    "Pendant with 2-Conductor 18-Gauge Pulley Cord",
    "Pendant with 3-Conductor 18-Gauge Pulley Cord",
    "Pendant with Overbraid Wire",
    "Pendant with Parallel Cord",
    "Ceiling Lights - Trapezoid",
    "TTLG Light",
    "Wall-Mounted Lights - Trapezoid",
    "Vintage Lighting",
    "Vintage Lightig",
    "Shipping",
}


def refresh_shopify_data(conn):
    """Refresh product data from both Shopify stores into SQLite."""
    print("Refreshing wire store...")
    from util.wire.wire_refresh_products import refresh_from_shopify as wire_refresh
    wire_refresh(conn)

    print("Refreshing audio store...")
    from util.audio.audio_refresh_products import refresh_from_shopify as audio_refresh
    audio_refresh(conn)


def calc_wire_value(conn):
    """Calculate wire inventory value from current Shopify data.

    Returns dict with keys: skus, units, value.
    """
    rows = conn.execute("""
        SELECT p.sku, p.qty, s.cost
        FROM products p
        JOIN (
            SELECT sku, cost FROM inventory_snapshots
            WHERE (sku, snapshot_date) IN (
                SELECT sku, MAX(snapshot_date) FROM inventory_snapshots GROUP BY sku
            )
        ) s ON p.sku = s.sku
        WHERE p.is_wire = 1 AND p.qty > 0 AND s.cost IS NOT NULL
    """).fetchall()

    total_value = sum(r["qty"] * r["cost"] for r in rows)
    total_units = sum(r["qty"] for r in rows)
    return {"skus": len(rows), "units": total_units, "value": round(total_value, 2)}


def calc_lamp_value(conn, excluded_skus):
    """Calculate lamp parts / hardware inventory value.

    For items with qty > 100, assumes actual qty is random 95-110 (no
    physical count yet for these items).

    Returns dict with keys: skus, units, value.
    """
    mto_placeholders = ",".join("?" * len(MADE_TO_ORDER_TYPES))

    # Items with known cost, excluding made-to-order and audio
    rows = conn.execute(f"""
        SELECT p.sku, p.qty, p.cost
        FROM products p
        WHERE p.is_wire = 0
          AND p.qty > 0 AND p.qty < 100000
          AND p.cost IS NOT NULL
          AND p.product_type NOT IN ({mto_placeholders})
          AND p.sku NOT LIKE 'SC-%' AND p.sku NOT LIKE 'SV-%'
          AND p.sku NOT LIKE 'TC-%' AND p.sku NOT LIKE 'TV-%'
    """, list(MADE_TO_ORDER_TYPES)).fetchall()

    total_value = 0.0
    total_units = 0
    sku_count = 0

    for r in rows:
        sku = r["sku"]
        if sku in excluded_skus:
            continue
        qty = r["qty"]
        if qty > 100:
            qty = random.randint(95, 110)
        total_value += qty * r["cost"]
        total_units += qty
        sku_count += 1

    return {"skus": sku_count, "units": total_units, "value": round(total_value, 2)}


def calc_audio_value(conn):
    """Calculate audio cable inventory value from PostgreSQL + SQLite costs.

    Counts available (unsold) cables from PostgreSQL, then looks up per-SKU
    cost from the SQLite products table.

    Returns dict with keys: skus, units, value.
    """
    import psycopg2
    from greenlight.config import DB_CONFIG

    pg = psycopg2.connect(**DB_CONFIG)
    try:
        cur = pg.cursor()
        cur.execute("""
            SELECT sku, COUNT(*) as qty
            FROM audio_cables
            WHERE shopify_order_gid IS NULL
            GROUP BY sku
            ORDER BY sku
        """)
        available = cur.fetchall()
    finally:
        pg.close()

    total_value = 0.0
    total_units = 0
    sku_count = 0

    for sku, qty in available:
        # Standard SKUs: look up cost directly
        cost_row = conn.execute(
            "SELECT cost FROM products WHERE sku = ?", (sku,)
        ).fetchone()

        if cost_row and cost_row["cost"]:
            total_value += qty * cost_row["cost"]
            total_units += qty
            sku_count += 1
        elif sku.endswith("-MISC"):
            # MISC cables: each has a unique Shopify SKU with its own cost
            # Sum individual costs from the special_baby shopify_sku entries
            pg2 = psycopg2.connect(**DB_CONFIG)
            try:
                cur2 = pg2.cursor()
                cur2.execute("""
                    SELECT sbt.shopify_sku
                    FROM audio_cables ac
                    JOIN special_baby_types sbt ON ac.special_baby_type_id = sbt.id
                    WHERE ac.shopify_order_gid IS NULL AND ac.sku = %s
                """, (sku,))
                for (shopify_sku,) in cur2.fetchall():
                    misc_cost = conn.execute(
                        "SELECT cost FROM products WHERE sku = ?", (shopify_sku,)
                    ).fetchone()
                    if misc_cost and misc_cost["cost"]:
                        total_value += misc_cost["cost"]
                        total_units += 1
                    else:
                        # Fall back to inventory_snapshots
                        snap = conn.execute(
                            "SELECT cost FROM inventory_snapshots WHERE sku = ? "
                            "ORDER BY snapshot_date DESC LIMIT 1", (shopify_sku,)
                        ).fetchone()
                        if snap and snap["cost"]:
                            total_value += snap["cost"]
                            total_units += 1
            finally:
                pg2.close()
            sku_count += 1

    return {"skus": sku_count, "units": total_units, "value": round(total_value, 2)}


def show_valuation(conn, query_date=None, limit=30):
    """Print daily valuations.

    If query_date is given, show that single date. Otherwise show the most
    recent entry, or up to `limit` rows with --all.
    """
    if query_date:
        rows = conn.execute(
            "SELECT * FROM daily_valuations WHERE valuation_date = ?",
            (query_date,),
        ).fetchall()
        if not rows:
            print(f"No valuation found for {query_date}.")
            return
    else:
        rows = conn.execute("""
            SELECT * FROM daily_valuations
            ORDER BY valuation_date DESC
            LIMIT ?
        """, (limit,)).fetchall()

    if not rows:
        print("No valuations recorded yet.")
        return

    # Write TSV file for easy Google Sheets import
    from util.wire.sundial_wire_db import DATA_DIR
    tsv_path = DATA_DIR / "valuations.tsv"
    with open(tsv_path, "w") as f:
        f.write("\t".join(["Date", "Wire", "Lamp Parts", "Audio", "Total"]) + "\n")
        for r in reversed(rows):
            total = r['wire_value'] + r['lamp_value'] + r['audio_value']
            f.write("\t".join([
                r['valuation_date'],
                f"{r['wire_value']:.2f}",
                f"{r['lamp_value']:.2f}",
                f"{r['audio_value']:.2f}",
                f"{total:.2f}",
            ]) + "\n")

    print(f"Wrote {tsv_path}")
    print()
    for r in reversed(rows):
        total = r['wire_value'] + r['lamp_value'] + r['audio_value']
        print(
            f"{r['valuation_date']}  "
            f"wire ${r['wire_value']:>10,.2f}  "
            f"lamp ${r['lamp_value']:>10,.2f}  "
            f"audio ${r['audio_value']:>10,.2f}  "
            f"total ${total:>10,.2f}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Nightly inventory valuation snapshot"
    )
    parser.add_argument(
        "--date", default=None,
        help="Override valuation date (YYYY-MM-DD, default: today)"
    )
    parser.add_argument(
        "--show", nargs="?", const="latest", default=None, metavar="DATE",
        help="Show valuations: no arg = latest, DATE = specific date, 'all' = history"
    )
    parser.add_argument(
        "--skip-refresh", action="store_true",
        help="Skip Shopify refresh (use existing data in SQLite)"
    )
    args = parser.parse_args()

    conn = get_db()
    init_db(conn)

    if args.show is not None:
        if args.show == "latest":
            show_valuation(conn, limit=1)
        elif args.show == "all":
            show_valuation(conn)
        else:
            show_valuation(conn, query_date=args.show)
        conn.close()
        return 0

    valuation_date = args.date or date.today().isoformat()

    print(f"Inventory Valuation for {valuation_date}")
    print("=" * 50)
    print()

    # Step 1: Refresh from Shopify
    if not args.skip_refresh:
        refresh_shopify_data(conn)
    else:
        print("Skipping Shopify refresh (using cached data)")
        print()

    # Step 2: Calculate values
    excluded = load_excluded_skus()

    wire = calc_wire_value(conn)
    print(f"Wire:       {wire['skus']:>4} SKUs  {wire['units']:>6} units  ${wire['value']:>10,.2f}")

    lamp = calc_lamp_value(conn, excluded)
    print(f"Lamp parts: {lamp['skus']:>4} SKUs  {lamp['units']:>6} units  ${lamp['value']:>10,.2f}")

    audio = calc_audio_value(conn)
    print(f"Audio:      {audio['skus']:>4} SKUs  {audio['units']:>6} units  ${audio['value']:>10,.2f}")

    total = wire["value"] + lamp["value"] + audio["value"]
    print(f"{'':>45s}  -----------")
    print(f"Total:                                         ${total:>10,.2f}")
    print()

    # Step 3: Store in DB
    upsert_daily_valuation(conn, valuation_date, wire, lamp, audio)
    print(f"Saved to daily_valuations for {valuation_date}")

    conn.close()
    print()
    print("Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
