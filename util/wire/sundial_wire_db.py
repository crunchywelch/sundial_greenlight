#!/usr/bin/env python3
"""
SQLite database layer for Sundial store data.

Provides schema management, bulk upserts, and CSV export for inventory
valuation and cost tracking. The SQLite database consolidates data from
both Shopify stores (wire + audio) into a single queryable store.

Usage:
    from util.wire.sundial_wire_db import get_db, init_db, upsert_products

    db = get_db()
    init_db(db)
    upsert_products(db, rows)
"""

import csv
import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent.parent / "data"
DEFAULT_DB = DATA_DIR / "sundial.db"

SCHEMA_SQL = """
-- Products from Shopify (wire + non-wire)
CREATE TABLE IF NOT EXISTS products (
    sku TEXT PRIMARY KEY,
    handle TEXT,
    title TEXT,
    option TEXT,
    product_type TEXT,
    qty INTEGER DEFAULT 0,
    price REAL,
    is_wire INTEGER DEFAULT 0,
    last_received TEXT,
    cost REAL,
    cost_vendor TEXT,
    cost_notes TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Vendor part number mappings (Satco, B&P)
CREATE TABLE IF NOT EXISTS vendor_parts (
    sku TEXT,
    vendor TEXT,
    part_number TEXT,
    PRIMARY KEY (sku, vendor)
);

-- Inventory snapshots (daily from Shopify)
CREATE TABLE IF NOT EXISTS inventory_snapshots (
    sku TEXT,
    snapshot_date TEXT,
    qty INTEGER,
    cost REAL,
    source TEXT,
    PRIMARY KEY (sku, snapshot_date)
);

-- Wire cost formula parameters (from wire_cost_data.yaml)
CREATE TABLE IF NOT EXISTS wire_cost_params (
    key TEXT PRIMARY KEY,
    category TEXT,
    value REAL
);

-- Wire material to product mapping
CREATE TABLE IF NOT EXISTS wire_materials (
    material_sku TEXT,
    description TEXT,
    wire_cost_key TEXT,
    product_family TEXT,
    PRIMARY KEY (material_sku, product_family)
);

-- Daily inventory valuation snapshots
CREATE TABLE IF NOT EXISTS daily_valuations (
    valuation_date TEXT PRIMARY KEY,
    wire_skus INTEGER,
    wire_units INTEGER,
    wire_value REAL,
    lamp_skus INTEGER,
    lamp_units INTEGER,
    lamp_value REAL,
    audio_skus INTEGER,
    audio_units INTEGER,
    audio_value REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def get_db(path=None):
    """Return a sqlite3 connection with row_factory set."""
    db_path = path or DEFAULT_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn=None):
    """Create all tables if they don't exist."""
    close = False
    if conn is None:
        conn = get_db()
        close = True
    conn.executescript(SCHEMA_SQL)

    # Migrate sku_costs columns into products (idempotent)
    for col, coltype in [("cost", "REAL"), ("cost_vendor", "TEXT"), ("cost_notes", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE products ADD COLUMN {col} {coltype}")
        except Exception:
            pass  # column already exists

    # Migrate data from sku_costs if it still exists
    try:
        conn.execute("""
            UPDATE products SET
                cost = (SELECT cost FROM sku_costs WHERE sku_costs.sku = products.sku),
                cost_vendor = (SELECT vendor FROM sku_costs WHERE sku_costs.sku = products.sku),
                cost_notes = (SELECT notes FROM sku_costs WHERE sku_costs.sku = products.sku)
            WHERE sku IN (SELECT sku FROM sku_costs)
              AND cost IS NULL
        """)
        conn.execute("DROP TABLE sku_costs")
    except Exception:
        pass  # sku_costs already dropped

    # Drop legacy tables/views if they exist
    conn.execute("DROP VIEW IF EXISTS inventory_reconciliation")
    conn.execute("DROP TABLE IF EXISTS inventory_events")
    conn.commit()
    if close:
        conn.close()


def upsert_products(conn, rows):
    """Bulk insert/update products.

    Each row is a dict with keys: sku, handle, title, option,
    product_type, qty, price, is_wire, and optionally cost,
    cost_vendor, cost_notes.
    """
    # Ensure optional cost fields default to None
    for row in rows:
        row.setdefault("cost", None)
        row.setdefault("cost_vendor", None)
        row.setdefault("cost_notes", None)
    conn.executemany(
        """INSERT INTO products (sku, handle, title, option,
                                 product_type, qty, price, is_wire,
                                 cost, cost_vendor, cost_notes, updated_at)
           VALUES (:sku, :handle, :title, :option,
                   :product_type, :qty, :price, :is_wire,
                   :cost, :cost_vendor, :cost_notes, CURRENT_TIMESTAMP)
           ON CONFLICT(sku) DO UPDATE SET
               handle=excluded.handle, title=excluded.title,
               option=excluded.option, product_type=excluded.product_type,
               qty=excluded.qty, price=excluded.price,
               is_wire=excluded.is_wire,
               cost=COALESCE(excluded.cost, products.cost),
               cost_vendor=COALESCE(excluded.cost_vendor, products.cost_vendor),
               cost_notes=COALESCE(excluded.cost_notes, products.cost_notes),
               updated_at=CURRENT_TIMESTAMP""",
        rows,
    )
    conn.commit()


def upsert_vendor_parts(conn, rows):
    """Bulk insert/update vendor part number mappings.

    Each row is a dict with keys: sku, vendor, part_number.
    """
    conn.executemany(
        """INSERT INTO vendor_parts (sku, vendor, part_number)
           VALUES (:sku, :vendor, :part_number)
           ON CONFLICT(sku, vendor) DO UPDATE SET
               part_number=excluded.part_number""",
        rows,
    )
    conn.commit()


def upsert_inventory_snapshot(conn, sku, snapshot_date, qty, cost, source):
    """Insert or update a single inventory snapshot."""
    conn.execute(
        """INSERT INTO inventory_snapshots (sku, snapshot_date, qty, cost, source)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(sku, snapshot_date) DO UPDATE SET
               qty=excluded.qty, cost=excluded.cost, source=excluded.source""",
        (sku, snapshot_date, qty, cost, source),
    )
    conn.commit()


def upsert_wire_cost_params(conn, rows):
    """Bulk insert/update wire cost params.

    Each row is a dict with keys: key, category, value.
    """
    conn.executemany(
        """INSERT INTO wire_cost_params (key, category, value)
           VALUES (:key, :category, :value)
           ON CONFLICT(key) DO UPDATE SET
               category=excluded.category, value=excluded.value""",
        rows,
    )
    conn.commit()


def upsert_wire_materials(conn, rows):
    """Bulk insert/update wire material mappings.

    Each row is a dict with keys: material_sku, description, wire_cost_key,
    product_family.
    """
    conn.executemany(
        """INSERT INTO wire_materials (material_sku, description, wire_cost_key,
                                       product_family)
           VALUES (:material_sku, :description, :wire_cost_key, :product_family)
           ON CONFLICT(material_sku, product_family) DO UPDATE SET
               description=excluded.description,
               wire_cost_key=excluded.wire_cost_key""",
        rows,
    )
    conn.commit()


def load_wire_cost_params(conn):
    """Load wire cost params grouped by category.

    Returns dict of {category: {key: value}}.
    """
    rows = conn.execute(
        "SELECT key, category, value FROM wire_cost_params"
    ).fetchall()
    result = {}
    for row in rows:
        cat = row["category"]
        if cat not in result:
            result[cat] = {}
        result[cat][row["key"]] = row["value"]
    return result


def load_wire_materials(conn):
    """Load wire material mappings.

    Returns list of dicts.
    """
    rows = conn.execute(
        "SELECT material_sku, description, wire_cost_key, product_family "
        "FROM wire_materials"
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_daily_valuation(conn, valuation_date, wire, lamp, audio):
    """Insert or update a daily valuation snapshot.

    wire/lamp/audio are each dicts with keys: skus, units, value.
    """
    conn.execute(
        """INSERT INTO daily_valuations
               (valuation_date, wire_skus, wire_units, wire_value,
                lamp_skus, lamp_units, lamp_value,
                audio_skus, audio_units, audio_value)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(valuation_date) DO UPDATE SET
               wire_skus=excluded.wire_skus, wire_units=excluded.wire_units,
               wire_value=excluded.wire_value,
               lamp_skus=excluded.lamp_skus, lamp_units=excluded.lamp_units,
               lamp_value=excluded.lamp_value,
               audio_skus=excluded.audio_skus, audio_units=excluded.audio_units,
               audio_value=excluded.audio_value,
               created_at=CURRENT_TIMESTAMP""",
        (valuation_date, wire["skus"], wire["units"], wire["value"],
         lamp["skus"], lamp["units"], lamp["value"],
         audio["skus"], audio["units"], audio["value"]),
    )
    conn.commit()


def export_csv(conn, query, output_path, params=None):
    """Run a query and write results to a CSV file.

    Returns the number of rows written.
    """
    cursor = conn.execute(query, params or ())
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for row in rows:
            writer.writerow(list(row))

    return len(rows)
