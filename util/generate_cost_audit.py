#!/usr/bin/env python3
"""
Generate cost audit CSVs for Shopify products.

Generates two reports:
  - docs/nonwire_cost_audit.csv  (lamp parts, bulbs, etc.)
  - docs/wire_cost_audit.csv     (wire/cable SKUs)

Data sources:
  - Shopify inventory worksheet (product details, qty, price, cost)
  - nonwire_costs.csv (our cost data with vendor and source)
  - Satco and B&P vendor worksheets (part numbers)

Usage:
    python util/generate_cost_audit.py            # Generate both
    python util/generate_cost_audit.py --wire      # Wire only
    python util/generate_cost_audit.py --nonwire   # Non-wire only
"""

import argparse
import csv
import re
import sys
from pathlib import Path

# Valid SKUs are alphanumeric with dots, dashes, slashes, and underscores.
# This filters out rows where HTML from Body column bled into the SKU field.
_VALID_SKU_RE = re.compile(r'^[A-Za-z0-9._/\-]+$')

DOCS = Path(__file__).parent.parent / "docs"
INVENTORY_CSV = DOCS / "wire_inventory_worksheet_2-4-2026.csv"
COST_CSV = DOCS / "nonwire_costs.csv"
SATCO_CSV = DOCS / "satco" / "Wire Inventory Worksheet - satco.csv"
BP_CSV = DOCS / "satco" / "Wire Inventory Worksheet - B&P.csv"
NONWIRE_OUTPUT = DOCS / "nonwire_cost_audit.csv"
WIRE_OUTPUT = DOCS / "wire_cost_audit.csv"


def load_cost_data():
    """Load our cost CSV into a dict of SKU -> {cost, vendor, notes}."""
    costs = {}
    with open(COST_CSV, newline="", encoding="utf-8") as f:
        lines = [line for line in f if not line.startswith("#")]
    reader = csv.DictReader(lines)
    for row in reader:
        sku = (row.get("SKU") or "").strip()
        if not sku:
            continue
        costs[sku] = {
            "cost": row.get("Cost", "").strip(),
            "vendor": row.get("Vendor", "").strip(),
            "notes": row.get("Notes", "").strip(),
        }
    return costs


def load_satco_part_numbers():
    """Load Satco SKU -> part number mapping."""
    parts = {}
    with open(SATCO_CSV, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if len(row) < 3:
                continue
            sku = row[0].strip()
            part = row[2].strip()
            if sku and part:
                parts[sku] = part
    return parts


def load_bp_part_numbers():
    """Load B&P SKU -> part number mapping."""
    parts = {}
    with open(BP_CSV, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if len(row) < 2:
                continue
            sku = row[0].strip()
            part = row[1].strip()
            if sku and part:
                parts[sku] = part
    return parts


def load_inventory(wire=False):
    """Load products from the Shopify inventory export.

    Args:
        wire: If True, load W-prefix (wire) SKUs. If False, load non-wire SKUs.
    """
    products = []
    with open(INVENTORY_CSV, newline="", encoding="utf-8") as f:
        # Skip grand-total row (line 0) by reading and discarding it
        f.readline()
        # Let csv.DictReader handle the rest properly (including multi-line
        # quoted fields like Body HTML)
        reader = csv.DictReader(f)
        for row in reader:
            sku = (row.get("Variant SKU") or "").strip()
            if not sku:
                continue
            # Skip garbage rows where HTML bled into the SKU field
            if not _VALID_SKU_RE.match(sku):
                continue
            # Filter by wire vs non-wire
            if wire and not sku.startswith("W"):
                continue
            if not wire and sku.startswith("W"):
                continue

            handle = (row.get("Handle") or "").strip()
            title = (row.get("Title") or "").strip()
            status = (row.get("Status") or "").strip()
            published = (row.get("Published") or "").strip()
            qty_str = (row.get("Variant Inventory Qty") or "").strip()
            price = (row.get("Variant Price") or "").strip()
            option1 = (row.get("Option1 Value") or "").strip()
            product_type = (row.get("Type") or "").strip()
            cost_str = (row.get("Cost per item") or "").strip()

            try:
                qty = int(float(qty_str)) if qty_str else 0
            except ValueError:
                qty = 0

            products.append({
                "sku": sku,
                "handle": handle,
                "title": title,
                "status": status,
                "published": published,
                "qty": qty,
                "price": price,
                "option": option1,
                "type": product_type,
                "csv_cost": cost_str,
            })

    return products


def carry_forward_fields(products):
    """Carry forward title/handle/status for variant rows.

    Shopify export only puts these on the first variant row of each product.
    """
    last = {"handle": "", "title": "", "status": "", "published": "", "type": ""}
    for p in products:
        for key in last:
            if p[key]:
                last[key] = p[key]
            else:
                p[key] = last[key]


def generate_nonwire(products):
    """Generate the non-wire cost audit CSV."""
    print("--- Non-Wire Audit ---")

    cost_data = load_cost_data()
    satco_parts = load_satco_part_numbers()
    bp_parts = load_bp_part_numbers()

    print(f"  Inventory products: {len(products)}")
    print(f"  Cost entries:       {len(cost_data)}")
    print(f"  Satco part maps:    {len(satco_parts)}")
    print(f"  B&P part maps:      {len(bp_parts)}")

    rows = []
    with_cost = 0
    without_cost = 0
    total_value = 0.0

    for p in products:
        sku = p["sku"]
        cd = cost_data.get(sku, {})
        cost = cd.get("cost", "")
        vendor = cd.get("vendor", "")
        source = cd.get("notes", "")

        part_number = satco_parts.get(sku, "") or bp_parts.get(sku, "")

        inv_value = ""
        if cost and p["qty"]:
            try:
                val = float(cost) * p["qty"]
                inv_value = f"{val:.2f}"
                total_value += val
            except ValueError:
                pass

        if cost:
            with_cost += 1
        else:
            without_cost += 1

        rows.append({
            "SKU": sku,
            "Handle": p["handle"],
            "Title": p["title"],
            "Option": p["option"],
            "Status": p["status"],
            "Published": p["published"],
            "Type": p["type"],
            "Qty": p["qty"],
            "Price": p["price"],
            "Cost": cost,
            "Inv Value": inv_value,
            "Vendor": vendor,
            "Part Number": part_number,
            "Cost Source": source,
        })

    fieldnames = [
        "SKU", "Handle", "Title", "Option", "Status", "Published", "Type",
        "Qty", "Price", "Cost", "Inv Value", "Vendor", "Part Number",
        "Cost Source",
    ]

    with open(NONWIRE_OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print()
    print(f"  Output:           {NONWIRE_OUTPUT.name}")
    print(f"  Total SKUs:       {len(rows)}")
    print(f"  With cost:        {with_cost}")
    print(f"  Without cost:     {without_cost}")
    print(f"  Total inv value:  ${total_value:,.2f}")
    print()


def generate_wire(products):
    """Generate the wire cost audit CSV."""
    print("--- Wire Audit ---")
    print(f"  Inventory products: {len(products)}")

    rows = []
    with_cost = 0
    without_cost = 0
    total_value = 0.0

    for p in products:
        sku = p["sku"]
        cost = p["csv_cost"]

        inv_value = ""
        if cost and p["qty"]:
            try:
                val = float(cost) * p["qty"]
                inv_value = f"{val:.2f}"
                total_value += val
            except ValueError:
                pass

        if cost:
            with_cost += 1
        else:
            without_cost += 1

        rows.append({
            "SKU": sku,
            "Handle": p["handle"],
            "Title": p["title"],
            "Option": p["option"],
            "Status": p["status"],
            "Published": p["published"],
            "Type": p["type"],
            "Qty": p["qty"],
            "Price": p["price"],
            "Cost": cost,
            "Inv Value": inv_value,
        })

    fieldnames = [
        "SKU", "Handle", "Title", "Option", "Status", "Published", "Type",
        "Qty", "Price", "Cost", "Inv Value",
    ]

    with open(WIRE_OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print()
    print(f"  Output:           {WIRE_OUTPUT.name}")
    print(f"  Total SKUs:       {len(rows)}")
    print(f"  With cost:        {with_cost}")
    print(f"  Without cost:     {without_cost}")
    print(f"  Total inv value:  ${total_value:,.2f}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Generate cost audit CSVs")
    parser.add_argument("--wire", action="store_true", help="Wire SKUs only")
    parser.add_argument("--nonwire", action="store_true", help="Non-wire SKUs only")
    args = parser.parse_args()

    # Default to both if neither flag specified
    do_wire = args.wire or not args.nonwire
    do_nonwire = args.nonwire or not args.wire

    print("Generating cost audit CSVs...")
    print()

    if do_nonwire:
        products = load_inventory(wire=False)
        carry_forward_fields(products)
        generate_nonwire(products)

    if do_wire:
        products = load_inventory(wire=True)
        carry_forward_fields(products)
        generate_wire(products)

    print("Done!")


if __name__ == "__main__":
    sys.exit(main() or 0)
