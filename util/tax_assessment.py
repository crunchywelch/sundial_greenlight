#!/usr/bin/env python3
"""
Generate Schedule E property tax assessment report from Shopify inventory.

Outputs a CSV in the assessor's format:
    Own/Other | Type | Description | Year of Manufacture | Year of purchase |
    Purchase price | Estimated market value

Products are grouped by category with subtotals. Only items with qty > 0
are included.

Usage:
    python util/tax_assessment.py              # Generate report
    python util/tax_assessment.py --year 2025  # Specify tax year
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from util.wire.sundial_db import DATA_DIR, get_db

OUTPUT_DIR = DATA_DIR / "exports"

# Map Shopify product_type to assessment category and group.
# type_key: (group_header, assessment_type)
# assessment_type is "Finished Goods or Products" or "Materials or Supplies"
CATEGORY_MAP = {
    # Non-wire finished goods
    "Bulbs": ("Bulbs", "Finished Goods or Products"),
    "Bulb Cages": ("Cages", "Finished Goods or Products"),
    "Canopies": ("Canopies", "Finished Goods or Products"),
    "Finials": ("Finials", "Finished Goods or Products"),
    "Harps": ("Harps", "Finished Goods or Products"),
    "Nipples": ("Nipples", "Finished Goods or Products"),
    "Plugs": ("Plugs", "Finished Goods or Products"),
    "Shade Holders": ("Shade Holders", "Finished Goods or Products"),
    "Sockets": ("Sockets", "Finished Goods or Products"),
    "Strain Reliefs": ("Strain Reliefs", "Finished Goods or Products"),
    "Switches": ("Switches", "Finished Goods or Products"),
    "Installed Switch": ("Switches", "Finished Goods or Products"),
    "Tape": ("Tape", "Finished Goods or Products"),
    "Miscellaneous": ("Miscellaneous", "Finished Goods or Products"),
    "Knob & Tube": ("Knobs, Tubes, Cleats", "Finished Goods or Products"),
    # Wire
    "Wire": ("Wire", "Finished Goods or Products"),
    "Wire Cutting": ("Wire", "Finished Goods or Products"),
    # Lighting / assembled products
    "Ceiling Lights - Trapezoid": ("Lighting", "Finished Goods or Products"),
    "TTLG Light": ("Lighting", "Finished Goods or Products"),
    "Wall-Mounted Lights - Trapezoid": ("Lighting", "Finished Goods or Products"),
    "Vintage Lighting": ("Lighting", "Finished Goods or Products"),
    "Vintage Lightig": ("Lighting", "Finished Goods or Products"),
    # Cord sets and pendants
    "Cord Set with 14g Pulley Cord": ("Cord Sets", "Finished Goods or Products"),
    "Cord Set with 16-Gauge Twisted Pair Wire": ("Cord Sets", "Finished Goods or Products"),
    "Cord Set with 18-Gauge Twisted Pair Wire": ("Cord Sets", "Finished Goods or Products"),
    "Cord Set with 2-Conductor 18-Gauge Pulley Cord": ("Cord Sets", "Finished Goods or Products"),
    "Cord Set with 20-Gauge Twisted Pair Wire": ("Cord Sets", "Finished Goods or Products"),
    "Cord Set with 22-Gauge Twisted Pair Wire": ("Cord Sets", "Finished Goods or Products"),
    "Cord Set with 3C 18g Pulley Cord": ("Cord Sets", "Finished Goods or Products"),
    "Cord Set with Overbraid Wire": ("Cord Sets", "Finished Goods or Products"),
    "Cord Set with Parallel Cord": ("Cord Sets", "Finished Goods or Products"),
    "Pendant with 14-Gauge Pulley Cord": ("Pendants", "Finished Goods or Products"),
    "Pendant with 16-Gauge Twisted Pair": ("Pendants", "Finished Goods or Products"),
    "Pendant with 18-Gauge Twisted Pair": ("Pendants", "Finished Goods or Products"),
    "Pendant with 2-Conductor 18-Gauge Pulley Cord": ("Pendants", "Finished Goods or Products"),
    "Pendant with 3-Conductor 18-Gauge Pulley Cord": ("Pendants", "Finished Goods or Products"),
    "Pendant with Overbraid Wire": ("Pendants", "Finished Goods or Products"),
    "Pendant with Parallel Cord": ("Pendants", "Finished Goods or Products"),
}

# Group display order
GROUP_ORDER = [
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
    "Wire",
    "Miscellaneous",
]

FIELDNAMES = [
    "Own/Other",
    "Type",
    "Description",
    "Year of Manufacture",
    "Year of purchase",
    "Purchase price",
    "Estimated market value",
]


def load_inventory(conn):
    """Load all in-stock products with costs from SQLite."""
    rows = conn.execute("""
        SELECT
            p.sku, p.title, p.option, p.product_type, p.qty, p.price,
            COALESCE(s.cost, sc.cost) AS unit_cost
        FROM products p
        LEFT JOIN (
            SELECT sku, cost FROM inventory_snapshots
            WHERE (sku, snapshot_date) IN (
                SELECT sku, MAX(snapshot_date) FROM inventory_snapshots GROUP BY sku
            )
        ) s ON p.sku = s.sku
        LEFT JOIN sku_costs sc ON p.sku = sc.sku
        WHERE p.qty > 0 AND p.qty <= 5000
        ORDER BY p.product_type, p.sku
    """).fetchall()
    return [dict(r) for r in rows]


def build_description(item):
    """Build a human-readable description from product data."""
    parts = []
    title = item["title"] or ""
    option = item["option"] or ""
    qty = item["qty"]

    parts.append(f"{qty}x")
    parts.append(item["sku"])
    if title:
        parts.append(f"- {title}")
    if option:
        parts.append(f"({option})")

    return " ".join(parts)


def generate_report(conn, tax_year):
    """Generate the assessment report."""
    items = load_inventory(conn)

    # Group items by assessment category
    groups = {}
    ungrouped = []

    for item in items:
        ptype = item["product_type"] or ""
        mapping = CATEGORY_MAP.get(ptype)
        if mapping:
            group_name, assess_type = mapping
            if group_name not in groups:
                groups[group_name] = {"type": assess_type, "items": []}
            groups[group_name]["items"].append(item)
        elif ptype and ptype != "Shipping":
            ungrouped.append(item)

    # Build output rows
    output_rows = []
    grand_cost = 0.0
    grand_value = 0.0

    # Title row
    output_rows.append({k: "" for k in FIELDNAMES})
    output_rows[0]["Own/Other"] = "Schedule E: Merchandise"

    # Header row
    output_rows.append({k: k for k in FIELDNAMES})

    ordered_groups = [g for g in GROUP_ORDER if g in groups]
    # Add any groups not in our predefined order
    for g in sorted(groups.keys()):
        if g not in ordered_groups:
            ordered_groups.append(g)

    for group_name in ordered_groups:
        gdata = groups[group_name]
        assess_type = gdata["type"]
        group_items = gdata["items"]

        # Group header (blank row then category name)
        output_rows.append({k: "" for k in FIELDNAMES})
        header_row = {k: "" for k in FIELDNAMES}
        header_row["Description"] = group_name
        output_rows.append(header_row)

        group_cost = 0.0
        group_value = 0.0

        for item in sorted(group_items, key=lambda x: x["sku"]):
            qty = item["qty"]
            unit_cost = item["unit_cost"]
            price = item["price"]

            purchase_price = round(qty * unit_cost, 2) if unit_cost else None
            market_value = round(qty * price, 2) if price else None

            if purchase_price:
                group_cost += purchase_price
            if market_value:
                group_value += market_value

            output_rows.append({
                "Own/Other": "own",
                "Type": assess_type,
                "Description": build_description(item),
                "Year of Manufacture": "",
                "Year of purchase": f"~last 3 years",
                "Purchase price": f"{purchase_price:.2f}" if purchase_price else "",
                "Estimated market value": f"{market_value:.2f}" if market_value else "",
            })

        # Group subtotal
        subtotal = {k: "" for k in FIELDNAMES}
        subtotal["Description"] = f"  Subtotal: {group_name}"
        subtotal["Purchase price"] = f"{group_cost:.2f}"
        subtotal["Estimated market value"] = f"{group_value:.2f}"
        output_rows.append(subtotal)

        grand_cost += group_cost
        grand_value += group_value

    # Handle ungrouped items
    if ungrouped:
        output_rows.append({k: "" for k in FIELDNAMES})
        header_row = {k: "" for k in FIELDNAMES}
        header_row["Description"] = "Other"
        output_rows.append(header_row)

        other_cost = 0.0
        other_value = 0.0
        for item in sorted(ungrouped, key=lambda x: x["sku"]):
            qty = item["qty"]
            unit_cost = item["unit_cost"]
            price = item["price"]
            purchase_price = round(qty * unit_cost, 2) if unit_cost else None
            market_value = round(qty * price, 2) if price else None
            if purchase_price:
                other_cost += purchase_price
            if market_value:
                other_value += market_value
            output_rows.append({
                "Own/Other": "own",
                "Type": "Finished Goods or Products",
                "Description": build_description(item),
                "Year of Manufacture": "",
                "Year of purchase": "~last 3 years",
                "Purchase price": f"{purchase_price:.2f}" if purchase_price else "",
                "Estimated market value": f"{market_value:.2f}" if market_value else "",
            })
        subtotal = {k: "" for k in FIELDNAMES}
        subtotal["Description"] = "  Subtotal: Other"
        subtotal["Purchase price"] = f"{other_cost:.2f}"
        subtotal["Estimated market value"] = f"{other_value:.2f}"
        output_rows.append(subtotal)
        grand_cost += other_cost
        grand_value += other_value

    # Grand total
    output_rows.append({k: "" for k in FIELDNAMES})
    total_row = {k: "" for k in FIELDNAMES}
    total_row["Description"] = "GRAND TOTAL"
    total_row["Purchase price"] = f"{grand_cost:.2f}"
    total_row["Estimated market value"] = f"{grand_value:.2f}"
    output_rows.append(total_row)

    return output_rows, grand_cost, grand_value


def main():
    parser = argparse.ArgumentParser(
        description="Generate Schedule E property tax assessment report"
    )
    parser.add_argument("--year", type=int, default=2025,
                        help="Tax year (default: 2025)")
    args = parser.parse_args()

    output_path = OUTPUT_DIR / f"schedule_e_{args.year}.csv"

    print(f"Generating Schedule E assessment for tax year {args.year}...")
    print()

    conn = get_db()
    rows, grand_cost, grand_value = generate_report(conn, args.year)
    conn.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        for row in rows:
            writer.writerow(row)

    # Count data rows (exclude headers, blanks, subtotals)
    data_rows = sum(1 for r in rows if r.get("Own/Other") == "own")

    print(f"  Output:              {output_path}")
    print(f"  Line items:          {data_rows}")
    print(f"  Total purchase cost: ${grand_cost:,.2f}")
    print(f"  Total market value:  ${grand_value:,.2f}")
    print()
    print("Done!")


if __name__ == "__main__":
    sys.exit(main() or 0)
