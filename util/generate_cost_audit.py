#!/usr/bin/env python3
"""
Generate cost audit CSVs for Shopify products.

Generates two reports from SQLite:
  - data/exports/nonwire_cost_audit.csv  (lamp parts, bulbs, etc.)
  - data/exports/wire_cost_audit.csv     (wire/cable SKUs)

Usage:
    python util/generate_cost_audit.py            # Generate both
    python util/generate_cost_audit.py --wire      # Wire only
    python util/generate_cost_audit.py --nonwire   # Non-wire only
"""

import argparse
import sys
from pathlib import Path

from sundial_db import DATA_DIR, get_db, export_csv

NONWIRE_OUTPUT = DATA_DIR / "exports" / "nonwire_cost_audit.csv"
WIRE_OUTPUT = DATA_DIR / "exports" / "wire_cost_audit.csv"


NONWIRE_QUERY = """
SELECT
    p.sku AS SKU,
    p.handle AS Handle,
    p.title AS Title,
    p.option AS Option,
    p.status AS Status,
    p.published AS Published,
    p.product_type AS Type,
    p.qty AS Qty,
    p.price AS Price,
    sc.cost AS Cost,
    CASE WHEN sc.cost IS NOT NULL AND p.qty > 0
         THEN ROUND(sc.cost * p.qty, 2) END AS "Inv Value",
    COALESCE(sc.vendor, '') AS Vendor,
    COALESCE(vp.part_number, '') AS "Part Number",
    COALESCE(sc.notes, '') AS "Cost Source"
FROM products p
LEFT JOIN sku_costs sc ON p.sku = sc.sku
LEFT JOIN (
    SELECT sku, part_number FROM vendor_parts
    WHERE vendor = 'Satco'
    UNION ALL
    SELECT sku, part_number FROM vendor_parts
    WHERE vendor = 'B&P' AND sku NOT IN (SELECT sku FROM vendor_parts WHERE vendor = 'Satco')
) vp ON p.sku = vp.sku
WHERE p.is_wire = 0
ORDER BY p.sku
"""

WIRE_QUERY = """
SELECT
    p.sku AS SKU,
    p.handle AS Handle,
    p.title AS Title,
    p.option AS Option,
    p.status AS Status,
    p.published AS Published,
    p.product_type AS Type,
    p.qty AS Qty,
    p.price AS Price,
    s.cost AS Cost,
    CASE WHEN s.cost IS NOT NULL AND p.qty > 0
         THEN ROUND(s.cost * p.qty, 2) END AS "Inv Value"
FROM products p
LEFT JOIN (
    SELECT sku, cost FROM inventory_snapshots
    WHERE (sku, snapshot_date) IN (
        SELECT sku, MAX(snapshot_date) FROM inventory_snapshots GROUP BY sku
    )
) s ON p.sku = s.sku
WHERE p.is_wire = 1
ORDER BY p.sku
"""


def generate_nonwire(conn):
    """Generate the non-wire cost audit CSV."""
    print("--- Non-Wire Audit ---")

    n = export_csv(conn, NONWIRE_QUERY, NONWIRE_OUTPUT)

    # Stats
    stats = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN sc.cost IS NOT NULL THEN 1 ELSE 0 END) as with_cost,
            SUM(CASE WHEN sc.cost IS NULL THEN 1 ELSE 0 END) as without_cost,
            COALESCE(SUM(CASE WHEN sc.cost IS NOT NULL AND p.qty > 0
                         THEN sc.cost * p.qty ELSE 0 END), 0) as total_value
        FROM products p
        LEFT JOIN sku_costs sc ON p.sku = sc.sku
        WHERE p.is_wire = 0
    """).fetchone()

    print(f"  Output:           {NONWIRE_OUTPUT.name}")
    print(f"  Total SKUs:       {n}")
    print(f"  With cost:        {stats['with_cost']}")
    print(f"  Without cost:     {stats['without_cost']}")
    print(f"  Total inv value:  ${stats['total_value']:,.2f}")
    print()


def generate_wire(conn):
    """Generate the wire cost audit CSV."""
    print("--- Wire Audit ---")

    n = export_csv(conn, WIRE_QUERY, WIRE_OUTPUT)

    stats = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN s.cost IS NOT NULL THEN 1 ELSE 0 END) as with_cost,
            SUM(CASE WHEN s.cost IS NULL THEN 1 ELSE 0 END) as without_cost,
            COALESCE(SUM(CASE WHEN s.cost IS NOT NULL AND p.qty > 0
                         THEN s.cost * p.qty ELSE 0 END), 0) as total_value
        FROM products p
        LEFT JOIN (
            SELECT sku, cost FROM inventory_snapshots
            WHERE (sku, snapshot_date) IN (
                SELECT sku, MAX(snapshot_date) FROM inventory_snapshots GROUP BY sku
            )
        ) s ON p.sku = s.sku
        WHERE p.is_wire = 1
    """).fetchone()

    print(f"  Output:           {WIRE_OUTPUT.name}")
    print(f"  Total SKUs:       {n}")
    print(f"  With cost:        {stats['with_cost']}")
    print(f"  Without cost:     {stats['without_cost']}")
    print(f"  Total inv value:  ${stats['total_value']:,.2f}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Generate cost audit CSVs")
    parser.add_argument("--wire", action="store_true", help="Wire SKUs only")
    parser.add_argument("--nonwire", action="store_true", help="Non-wire SKUs only")
    args = parser.parse_args()

    do_wire = args.wire or not args.nonwire
    do_nonwire = args.nonwire or not args.wire

    print("Generating cost audit CSVs...")
    print()

    conn = get_db()

    if do_nonwire:
        generate_nonwire(conn)

    if do_wire:
        generate_wire(conn)

    conn.close()
    print("Done!")


if __name__ == "__main__":
    sys.exit(main() or 0)
