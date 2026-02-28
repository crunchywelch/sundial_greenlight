#!/usr/bin/env python3
"""
Import all source data files into the Sundial SQLite database.

Reads CSV, YAML, and worksheet files from the data/ directory and populates
all tables. Safe to re-run — uses INSERT OR REPLACE for all tables.

Usage:
    python util/import_sundial_data.py
"""

import csv
import re
import sys
from pathlib import Path

import yaml

from sundial_wire_db import (
    DATA_DIR,
    get_db,
    init_db,
    insert_inventory_events,
    upsert_products,
    upsert_sku_costs,
    upsert_vendor_parts,
    upsert_wire_cost_params,
    upsert_wire_materials,
)

# File paths
INVENTORY_CSV = DATA_DIR / "imports" / "wire_inventory_worksheet_2-4-2026.csv"
COST_CSV = DATA_DIR / "nonwire_costs.csv"
YAML_PATH = DATA_DIR / "wire_cost_data.yaml"
SATCO_CSV = DATA_DIR / "vendor" / "satco" / "Wire Inventory Worksheet - satco.csv"
BP_CSV = DATA_DIR / "vendor" / "satco" / "Wire Inventory Worksheet - B&P.csv"
EVENTS_CSV = DATA_DIR / "exports" / "inventory_events_2026.csv"

# Valid SKUs: alphanumeric with dots, dashes, slashes, underscores
_VALID_SKU_RE = re.compile(r'^[A-Za-z0-9._/\-]+$')


def import_products(conn):
    """Import products from the Shopify inventory export CSV."""
    if not INVENTORY_CSV.exists():
        print(f"  SKIP: {INVENTORY_CSV.name} not found (gitignored)")
        return 0

    with open(INVENTORY_CSV, newline="", encoding="utf-8") as f:
        f.readline()  # skip grand-total row
        reader = csv.DictReader(f)

        rows = []
        # Carry-forward state for Shopify export format
        last = {"handle": "", "title": "", "status": "", "published": "", "type": ""}

        for row in reader:
            sku = (row.get("Variant SKU") or "").strip()
            if not sku or not _VALID_SKU_RE.match(sku):
                continue

            handle = (row.get("Handle") or "").strip()
            title = (row.get("Title") or "").strip()
            status = (row.get("Status") or "").strip()
            published = (row.get("Published") or "").strip()
            product_type = (row.get("Type") or "").strip()

            # Carry forward title/handle/status for variant rows
            for key, field in [("handle", handle), ("title", title),
                               ("status", status), ("published", published),
                               ("type", product_type)]:
                if field:
                    last[key] = field

            handle = handle or last["handle"]
            title = title or last["title"]
            status = status or last["status"]
            published = published or last["published"]
            product_type = product_type or last["type"]

            qty_str = (row.get("Variant Inventory Qty") or "").strip()
            price_str = (row.get("Variant Price") or "").strip()
            cost_str = (row.get("Cost per item") or "").strip()
            option = (row.get("Option1 Value") or "").strip()

            try:
                qty = int(float(qty_str)) if qty_str else 0
            except ValueError:
                qty = 0
            try:
                price = float(price_str) if price_str else None
            except ValueError:
                price = None

            rows.append({
                "sku": sku,
                "handle": handle,
                "title": title,
                "option": option,
                "status": status,
                "published": published,
                "product_type": product_type,
                "qty": qty,
                "price": price,
                "is_wire": 1 if sku.startswith("W") else 0,
            })

    upsert_products(conn, rows)
    return len(rows)


def import_sku_costs(conn):
    """Import non-wire costs from nonwire_costs.csv."""
    with open(COST_CSV, newline="", encoding="utf-8") as f:
        lines = [line for line in f if not line.startswith("#")]

    reader = csv.DictReader(lines)
    rows = []
    for row in reader:
        sku = (row.get("SKU") or "").strip()
        cost_str = (row.get("Cost") or "").strip()
        if not sku or not cost_str:
            continue
        try:
            rows.append({
                "sku": sku,
                "cost": float(cost_str),
                "vendor": (row.get("Vendor") or "").strip(),
                "notes": (row.get("Notes") or "").strip(),
            })
        except ValueError:
            continue

    upsert_sku_costs(conn, rows)
    return len(rows)


def import_satco_parts(conn):
    """Import Satco SKU -> part number mappings."""
    rows = []
    with open(SATCO_CSV, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if len(row) < 3:
                continue
            sku = row[0].strip()
            part = row[2].strip()
            if sku and part:
                rows.append({"sku": sku, "vendor": "Satco", "part_number": part})

    upsert_vendor_parts(conn, rows)
    return len(rows)


def import_bp_parts(conn):
    """Import B&P SKU -> part number mappings."""
    rows = []
    with open(BP_CSV, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if len(row) < 2:
                continue
            sku = row[0].strip()
            part = row[1].strip()
            if sku and part:
                rows.append({"sku": sku, "vendor": "B&P", "part_number": part})

    upsert_vendor_parts(conn, rows)
    return len(rows)


def import_inventory_events(conn):
    """Import inventory events from cached CSV."""
    if not EVENTS_CSV.exists():
        print(f"  SKIP: {EVENTS_CSV.name} not found")
        return 0

    rows = []
    with open(EVENTS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            change_str = (row.get("change") or "").strip()
            try:
                change = int(float(change_str)) if change_str else 0
            except ValueError:
                change = 0
            rows.append({
                "event_date": (row.get("date") or "").strip(),
                "sku": (row.get("sku") or "").strip(),
                "change": change,
                "reason": (row.get("reason") or "").strip(),
                "state": (row.get("state") or "").strip(),
                "staff": (row.get("staff") or "").strip(),
            })

    insert_inventory_events(conn, rows)
    return len(rows)


def import_wire_cost_data(conn):
    """Import wire cost parameters and materials from YAML."""
    with open(YAML_PATH) as f:
        data = yaml.safe_load(f)

    params = []

    # Spool costs
    for key, value in data.get("spool_costs", {}).items():
        params.append({"key": key, "category": "spool_cost", "value": value})

    # Yarn costs
    for key, value in data.get("yarn_costs", {}).items():
        params.append({"key": key, "category": "yarn_cost", "value": value})

    # Yarn per 100ft
    for key, value in data.get("yarn_per_100ft", {}).items():
        params.append({"key": str(key), "category": "yarn_per_100ft", "value": value})

    # Wire costs
    for key, value in data.get("wire_costs", {}).items():
        params.append({"key": key, "category": "wire_cost", "value": value})

    upsert_wire_cost_params(conn, params)

    # Materials
    mat_rows = []
    for mat_sku, mat_data in data.get("materials", {}).items():
        desc = mat_data.get("description", "")
        wire_cost_key = mat_data.get("wire_cost_key", "")
        for product_family in mat_data.get("products", []):
            mat_rows.append({
                "material_sku": mat_sku,
                "description": desc,
                "wire_cost_key": wire_cost_key,
                "product_family": product_family,
            })

    upsert_wire_materials(conn, mat_rows)
    return len(params), len(mat_rows)


def main():
    print("Importing Sundial data into SQLite...")
    print(f"Database: {DATA_DIR / 'sundial.db'}")
    print()

    conn = get_db()
    init_db(conn)

    # Products from Shopify export
    print("Importing products from Shopify inventory export...")
    n = import_products(conn)
    print(f"  {n} products")

    # Non-wire costs
    print("Importing non-wire costs...")
    n = import_sku_costs(conn)
    print(f"  {n} SKU costs")

    # Vendor part numbers
    print("Importing Satco part numbers...")
    n = import_satco_parts(conn)
    print(f"  {n} Satco mappings")

    print("Importing B&P part numbers...")
    n = import_bp_parts(conn)
    print(f"  {n} B&P mappings")

    # Inventory events
    print("Importing inventory events...")
    n = import_inventory_events(conn)
    print(f"  {n} events")

    # Wire cost data
    print("Importing wire cost data from YAML...")
    n_params, n_mats = import_wire_cost_data(conn)
    print(f"  {n_params} cost params, {n_mats} material mappings")

    # Summary
    print()
    print("Summary:")
    for table in ["products", "sku_costs", "vendor_parts", "inventory_events",
                   "inventory_snapshots", "wire_cost_params", "wire_materials"]:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:25} {count:>6} rows")

    conn.close()
    print()
    print("Done!")


if __name__ == "__main__":
    sys.exit(main() or 0)
