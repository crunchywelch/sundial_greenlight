#!/usr/bin/env python3
"""
Inventory valuation report by category.

Queries inventory_snapshots for a given date and breaks down value into
four categories: Wire, Knob & Tube, Audio Cables, and Lamp Hardware.

Usage:
    python util/valuation_report.py                    # Most recent snapshot
    python util/valuation_report.py 2026-03-18         # Specific date
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from util.wire.sundial_wire_db import get_db

CATEGORY_SQL = """
    CASE
        WHEN sku LIKE 'W%%' THEN 'Wire'
        WHEN sku LIKE 'CTUBE%%' OR sku LIKE 'CCLEAT%%' OR sku LIKE 'CKNOB%%' THEN 'Knob & Tube'
        WHEN sku LIKE 'SC-%%' OR sku LIKE 'SV-%%'
          OR sku LIKE 'TC-%%' OR sku LIKE 'TV-%%' THEN 'Audio Cables'
        ELSE 'Lamp Hardware'
    END
"""

CATEGORY_ORDER = ['Wire', 'Knob & Tube', 'Audio Cables', 'Lamp Hardware']


def get_latest_date(conn):
    row = conn.execute(
        "SELECT MAX(snapshot_date) FROM inventory_snapshots"
    ).fetchone()
    return row[0] if row else None


def run_report(conn, report_date):
    rows = conn.execute(f"""
        SELECT
            {CATEGORY_SQL} AS category,
            COUNT(*) AS skus,
            SUM(qty) AS units,
            ROUND(SUM(qty * cost)::numeric, 2) AS value
        FROM inventory_snapshots
        WHERE snapshot_date = %s
          AND qty > 0 AND qty < 100000 AND cost IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """, (report_date,)).fetchall()

    if not rows:
        print(f"No snapshot data for {report_date}.")
        return None

    results = {r["category"]: r for r in rows}

    print(f"Inventory Valuation — {report_date}")
    print("=" * 58)

    grand_skus = 0
    grand_units = 0
    grand_value = 0.0

    for cat in CATEGORY_ORDER:
        r = results.get(cat)
        if r:
            skus, units, value = r["skus"], r["units"], float(r["value"])
            print(f"  {cat:<16} {skus:>4} SKUs  {units:>6} units  ${value:>10,.2f}")
            grand_skus += skus
            grand_units += units
            grand_value += value
        else:
            print(f"  {cat:<16}    0 SKUs       0 units  $      0.00")

    print(f"  {'':>38s}  -----------")
    print(f"  {'Total':<16} {grand_skus:>4} SKUs  {grand_units:>6} units  ${grand_value:>10,.2f}")
    print()

    return grand_value


def main():
    report_date = sys.argv[1] if len(sys.argv) > 1 else None

    conn = get_db()

    if not report_date:
        report_date = get_latest_date(conn)
        if not report_date:
            print("No snapshot data found.")
            conn.close()
            return 1

    run_report(conn, report_date)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
