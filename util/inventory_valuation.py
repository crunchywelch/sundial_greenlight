#!/usr/bin/env python3
"""
Generate a point-in-time inventory valuation report.

Back-calculates historical inventory levels by taking the most recent
inventory snapshot for each SKU and subtracting net inventory changes
that occurred after the target date.

Usage:
    python util/inventory_valuation.py --date 2025-12-31
    python util/inventory_valuation.py --date 2025-12-31 --csv
    python util/inventory_valuation.py --date 2025-12-31 --detail
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from util.wire.sundial_wire_db import DATA_DIR, get_db, init_db, export_csv
from util.tax_assessment import load_excluded_skus

OUTPUT_DIR = DATA_DIR / "exports"

# Category grouping: product_type -> display group
CATEGORY_MAP = {
    # Wire
    "Wire": "Wire",
    "Wire Cutting": "Wire",
    # Audio cables
    "Audio Cable": "Audio Cables",
    # Non-wire finished goods
    "Bulbs": "Bulbs",
    "Bulb Cages": "Cages",
    "Canopies": "Canopies",
    "Finials": "Finials",
    "Harps": "Harps",
    "Nipples": "Nipples",
    "Plugs": "Plugs",
    "Shade Holders": "Shade Holders",
    "Sockets": "Sockets",
    "Strain Reliefs": "Strain Reliefs",
    "Switches": "Switches",
    "Installed Switch": "Switches",
    "Tape": "Tape",
    "Miscellaneous": "Miscellaneous",
    "Knob & Tube": "Knobs, Tubes, Cleats",
    # Cord sets and pendants
    "Cord Set with 14g Pulley Cord": "Cord Sets",
    "Cord Set with 16-Gauge Twisted Pair Wire": "Cord Sets",
    "Cord Set with 18-Gauge Twisted Pair Wire": "Cord Sets",
    "Cord Set with 2-Conductor 18-Gauge Pulley Cord": "Cord Sets",
    "Cord Set with 20-Gauge Twisted Pair Wire": "Cord Sets",
    "Cord Set with 22-Gauge Twisted Pair Wire": "Cord Sets",
    "Cord Set with 3C 18g Pulley Cord": "Cord Sets",
    "Cord Set with Overbraid Wire": "Cord Sets",
    "Cord Set with Parallel Cord": "Cord Sets",
    "Pendant with 14-Gauge Pulley Cord": "Pendants",
    "Pendant with 16-Gauge Twisted Pair": "Pendants",
    "Pendant with 18-Gauge Twisted Pair": "Pendants",
    "Pendant with 2-Conductor 18-Gauge Pulley Cord": "Pendants",
    "Pendant with 3-Conductor 18-Gauge Pulley Cord": "Pendants",
    "Pendant with Overbraid Wire": "Pendants",
    "Pendant with Parallel Cord": "Pendants",
    # Lighting
    "Ceiling Lights - Trapezoid": "Lighting",
    "TTLG Light": "Lighting",
    "Wall-Mounted Lights - Trapezoid": "Lighting",
    "Vintage Lighting": "Lighting",
    "Vintage Lightig": "Lighting",
}

GROUP_ORDER = [
    "Wire",
    "Audio Cables",
    "Knobs, Tubes, Cleats",
    "Bulbs",
    "Cages",
    "Canopies",
    "Finials",
    "Harps",
    "Nipples",
    "Plugs",
    "Shade Holders",
    "Sockets",
    "Strain Reliefs",
    "Switches",
    "Tape",
    "Cord Sets",
    "Pendants",
    "Lighting",
    "Miscellaneous",
]

VALUATION_QUERY = """
SELECT
    s.sku,
    p.title,
    p.option,
    p.product_type,
    p.is_wire,
    s.qty AS snapshot_qty,
    s.snapshot_date,
    COALESCE(e.net_change, 0) AS changes_after_date,
    s.qty - COALESCE(e.net_change, 0) AS qty_at_date,
    CASE WHEN p.is_wire = 1 THEN s.cost ELSE sc.cost END AS unit_cost,
    (s.qty - COALESCE(e.net_change, 0)) *
        CASE WHEN p.is_wire = 1 THEN s.cost ELSE sc.cost END AS value_at_date
FROM inventory_snapshots s
LEFT JOIN (
    SELECT sku, SUM(change) AS net_change
    FROM inventory_events
    WHERE event_date > :target_date
      AND state = 'available'
    GROUP BY sku
) e ON s.sku = e.sku
LEFT JOIN products p ON s.sku = p.sku
LEFT JOIN sku_costs sc ON s.sku = sc.sku AND p.is_wire = 0
WHERE s.snapshot_date = (
    SELECT MAX(snapshot_date) FROM inventory_snapshots s2 WHERE s2.sku = s.sku
)
  AND s.qty - COALESCE(e.net_change, 0) > 0
ORDER BY p.product_type, s.sku
"""


def load_valuation(conn, target_date, excluded_skus):
    """Load inventory valuation data for a target date.

    Returns list of dicts with sku, title, product_type, qty, unit_cost, value.
    """
    rows = conn.execute(VALUATION_QUERY, {"target_date": target_date}).fetchall()
    items = []
    for r in rows:
        sku = r["sku"]
        if sku in excluded_skus:
            continue
        unit_cost = r["unit_cost"]
        if unit_cost is None:
            continue
        qty = r["qty_at_date"]
        items.append({
            "sku": sku,
            "title": r["title"] or "",
            "option": r["option"] or "",
            "product_type": r["product_type"] or "",
            "is_wire": r["is_wire"],
            "qty": qty,
            "unit_cost": unit_cost,
            "value": round(qty * unit_cost, 2),
            "snapshot_qty": r["snapshot_qty"],
            "changes_after": r["changes_after_date"],
            "snapshot_date": r["snapshot_date"],
        })
    return items


def format_description(item):
    """Build a compact description for terminal display."""
    parts = [item["title"]]
    if item["option"] and item["option"] != "Default Title":
        parts.append(f"({item['option']})")
    return " ".join(parts)


def print_report(items, target_date, detail=False):
    """Print the inventory valuation report to the terminal."""
    print()
    print(f"Inventory Valuation as of {target_date}")
    print("=" * 72)

    # Group items
    groups = {}
    ungrouped = []
    for item in items:
        group = CATEGORY_MAP.get(item["product_type"])
        if group:
            groups.setdefault(group, []).append(item)
        else:
            ungrouped.append(item)

    ordered = [g for g in GROUP_ORDER if g in groups]
    for g in sorted(groups.keys()):
        if g not in ordered:
            ordered.append(g)
    if ungrouped:
        ordered.append("Other")
        groups["Other"] = ungrouped

    grand_total = 0.0
    grand_units = 0

    for group_name in ordered:
        group_items = groups.get(group_name, [])
        if not group_items:
            continue

        print()
        print(f"  {group_name}")
        print(f"  {'-' * 68}")

        group_total = 0.0
        group_units = 0

        for item in sorted(group_items, key=lambda x: x["sku"]):
            value = item["value"]
            group_total += value
            group_units += item["qty"]

            if detail:
                desc = format_description(item)
                if len(desc) > 32:
                    desc = desc[:29] + "..."
                print(
                    f"    {item['sku']:22s} {desc:32s} "
                    f"{item['qty']:>5d} x ${item['unit_cost']:>8.2f}  = ${value:>10,.2f}"
                )

        print(
            f"    {'':22s} {'Subtotal: ' + group_name:>32s} "
            f"{group_units:>5d} items          ${group_total:>10,.2f}"
        )

        grand_total += group_total
        grand_units += group_units

    print()
    print(f"  {'=' * 68}")
    print(
        f"    {'':22s} {'TOTAL INVENTORY VALUE':>32s} "
        f"{grand_units:>5d} items          ${grand_total:>10,.2f}"
    )
    print()

    return grand_total


def export_valuation_csv(conn, target_date, items):
    """Export valuation data to CSV."""
    output_path = OUTPUT_DIR / f"inventory_valuation_{target_date}.csv"

    # Build rows for CSV
    import csv

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["sku", "title", "product_type", "group", "qty", "unit_cost", "total_value"])
        for item in sorted(items, key=lambda x: (x["product_type"], x["sku"])):
            group = CATEGORY_MAP.get(item["product_type"], "Other")
            writer.writerow([
                item["sku"],
                item["title"],
                item["product_type"],
                group,
                item["qty"],
                f"{item['unit_cost']:.2f}",
                f"{item['value']:.2f}",
            ])

    return output_path, len(items)


def main():
    parser = argparse.ArgumentParser(
        description="Generate point-in-time inventory valuation report"
    )
    parser.add_argument(
        "--date", required=True,
        help="Target date for valuation (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--csv", action="store_true",
        help="Export results to CSV"
    )
    parser.add_argument(
        "--detail", action="store_true",
        help="Show per-SKU breakdown in terminal output"
    )
    args = parser.parse_args()

    target_date = args.date

    conn = get_db()
    init_db(conn)

    excluded = load_excluded_skus()
    items = load_valuation(conn, target_date, excluded)

    if not items:
        print(f"No inventory data found for {target_date}.")
        print("Make sure you've run the product refresh and inventory event scripts first.")
        conn.close()
        return 1

    grand_total = print_report(items, target_date, detail=args.detail)

    # Summary stats
    wire_items = [i for i in items if i["is_wire"]]
    nonwire_items = [i for i in items if not i["is_wire"]]
    wire_value = sum(i["value"] for i in wire_items)
    nonwire_value = sum(i["value"] for i in nonwire_items)

    print(f"  Wire SKUs:     {len(wire_items):>4}  (${wire_value:>10,.2f})")
    print(f"  Non-wire SKUs: {len(nonwire_items):>4}  (${nonwire_value:>10,.2f})")
    print(f"  Total SKUs:    {len(items):>4}  (${grand_total:>10,.2f})")
    print()

    no_cost = conn.execute(
        """SELECT s.sku, p.title, s.qty
           FROM inventory_snapshots s
           LEFT JOIN products p ON s.sku = p.sku
           LEFT JOIN sku_costs sc ON s.sku = sc.sku
           WHERE s.snapshot_date = (
               SELECT MAX(snapshot_date) FROM inventory_snapshots s2 WHERE s2.sku = s.sku
           )
             AND s.qty > 0
             AND CASE WHEN p.is_wire = 1 THEN s.cost ELSE sc.cost END IS NULL
           ORDER BY s.sku"""
    ).fetchall()
    no_cost = [r for r in no_cost if r["sku"] not in excluded]

    if no_cost:
        print(f"  Warning: {len(no_cost)} SKU(s) with stock but no cost (excluded from totals):")
        for r in no_cost:
            print(f"    {r['sku']:22s} qty={r['qty']}  {r['title'] or ''}")
        print()

    if args.csv:
        path, n = export_valuation_csv(conn, target_date, items)
        print(f"  Exported {n} rows to {path}")
        print()

    conn.close()
    print("Done!")


if __name__ == "__main__":
    sys.exit(main() or 0)
