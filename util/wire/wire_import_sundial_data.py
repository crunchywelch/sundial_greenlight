#!/usr/bin/env python3
"""
Import vendor data and wire cost parameters into the Sundial SQLite database.

Imports wire cost calculation parameters from YAML and vendor part number
mappings from CSV. Safe to re-run — uses INSERT OR REPLACE for all tables.

Product data and costs are synced live from Shopify via wire_refresh_products.py.
Inventory events are pulled live via wire_pull_inventory_events.py.

Usage:
    python util/wire/wire_import_sundial_data.py
"""

import csv
import sys
from pathlib import Path

import yaml

from sundial_wire_db import (
    DATA_DIR,
    get_db,
    init_db,
    upsert_vendor_parts,
    upsert_wire_cost_params,
    upsert_wire_materials,
)

# File paths
YAML_PATH = DATA_DIR / "wire_cost_data.yaml"
SATCO_CSV = DATA_DIR / "vendor" / "satco" / "Wire Inventory Worksheet - satco.csv"
BP_CSV = DATA_DIR / "vendor" / "satco" / "Wire Inventory Worksheet - B&P.csv"


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
    print("Importing vendor data and wire cost parameters...")
    print(f"Database: {DATA_DIR / 'sundial.db'}")
    print()

    conn = get_db()
    init_db(conn)

    # Vendor part numbers
    print("Importing Satco part numbers...")
    n = import_satco_parts(conn)
    print(f"  {n} Satco mappings")

    print("Importing B&P part numbers...")
    n = import_bp_parts(conn)
    print(f"  {n} B&P mappings")

    # Wire cost data
    print("Importing wire cost data from YAML...")
    n_params, n_mats = import_wire_cost_data(conn)
    print(f"  {n_params} cost params, {n_mats} material mappings")

    # Summary
    print()
    print("Summary:")
    for table in ["vendor_parts", "wire_cost_params", "wire_materials"]:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:25} {count:>6} rows")

    conn.close()
    print()
    print("Done!")


if __name__ == "__main__":
    sys.exit(main() or 0)
