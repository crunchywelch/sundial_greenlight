#!/usr/bin/env python3
"""
SQLite database layer for Sundial Wire store data.

Provides schema management, bulk upserts, and CSV export for the year-end
reconciliation workflow. The SQLite database consolidates data from Shopify
exports, vendor worksheets, and cost CSVs into a single queryable store.

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
    status TEXT,
    published TEXT,
    product_type TEXT,
    qty INTEGER DEFAULT 0,
    price REAL,
    is_wire INTEGER DEFAULT 0,
    last_received TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Costs for non-wire SKUs (from nonwire_costs.csv)
CREATE TABLE IF NOT EXISTS sku_costs (
    sku TEXT PRIMARY KEY,
    cost REAL,
    vendor TEXT,
    notes TEXT
);

-- Vendor part number mappings (Satco, B&P)
CREATE TABLE IF NOT EXISTS vendor_parts (
    sku TEXT,
    vendor TEXT,
    part_number TEXT,
    PRIMARY KEY (sku, vendor)
);

-- Inventory events from ShopifyQL (pulled via API)
CREATE TABLE IF NOT EXISTS inventory_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_date TEXT,
    sku TEXT,
    change INTEGER,
    reason TEXT,
    state TEXT,
    staff TEXT
);

-- Dedupe index for inventory events
CREATE UNIQUE INDEX IF NOT EXISTS idx_inventory_events_dedup
    ON inventory_events(event_date, sku, change, reason, state, staff);

-- Inventory snapshots (post physical count + corrected)
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

-- View: Dec 31 2025 reconciliation
CREATE VIEW IF NOT EXISTS inventory_reconciliation AS
SELECT
    s.sku,
    s.qty AS current_qty,
    COALESCE(e.net_change, 0) AS net_change_2026,
    s.qty - COALESCE(e.net_change, 0) AS dec31_qty,
    p.price,
    COALESCE(sc.cost, s.cost) AS unit_cost,
    (s.qty - COALESCE(e.net_change, 0)) *
        COALESCE(sc.cost, s.cost) AS dec31_value
FROM inventory_snapshots s
LEFT JOIN (
    SELECT sku, SUM(change) AS net_change
    FROM inventory_events
    WHERE event_date >= '2026-01-01'
      AND state = 'available'
    GROUP BY sku
) e ON s.sku = e.sku
LEFT JOIN products p ON s.sku = p.sku
LEFT JOIN sku_costs sc ON s.sku = sc.sku
WHERE s.source = 'physical_count';
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
    # Migrate: add last_received column if missing (existing databases)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(products)").fetchall()]
    if "last_received" not in cols:
        conn.execute("ALTER TABLE products ADD COLUMN last_received TEXT")
    conn.commit()
    if close:
        conn.close()


def upsert_products(conn, rows):
    """Bulk insert/update products.

    Each row is a dict with keys: sku, handle, title, option, status,
    published, product_type, qty, price, is_wire.
    """
    conn.executemany(
        """INSERT INTO products (sku, handle, title, option, status, published,
                                 product_type, qty, price, is_wire, updated_at)
           VALUES (:sku, :handle, :title, :option, :status, :published,
                   :product_type, :qty, :price, :is_wire, CURRENT_TIMESTAMP)
           ON CONFLICT(sku) DO UPDATE SET
               handle=excluded.handle, title=excluded.title,
               option=excluded.option, status=excluded.status,
               published=excluded.published, product_type=excluded.product_type,
               qty=excluded.qty, price=excluded.price,
               is_wire=excluded.is_wire, updated_at=CURRENT_TIMESTAMP""",
        rows,
    )
    conn.commit()


def upsert_sku_costs(conn, rows):
    """Bulk insert/update non-wire costs.

    Each row is a dict with keys: sku, cost, vendor, notes.
    """
    conn.executemany(
        """INSERT INTO sku_costs (sku, cost, vendor, notes)
           VALUES (:sku, :cost, :vendor, :notes)
           ON CONFLICT(sku) DO UPDATE SET
               cost=excluded.cost, vendor=excluded.vendor,
               notes=excluded.notes""",
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


def insert_inventory_events(conn, rows):
    """Append inventory events, skipping duplicates.

    Each row is a dict with keys: event_date, sku, change, reason, state, staff.
    """
    conn.executemany(
        """INSERT OR IGNORE INTO inventory_events
               (event_date, sku, change, reason, state, staff)
           VALUES (:event_date, :sku, :change, :reason, :state, :staff)""",
        rows,
    )
    conn.commit()


def update_last_received(conn):
    """Update products.last_received from inventory events.

    Sets last_received to the most recent event date where inventory was
    added (change > 0) for each SKU.
    """
    conn.execute("""
        UPDATE products SET last_received = (
            SELECT MAX(event_date) FROM inventory_events
            WHERE inventory_events.sku = products.sku
              AND change > 0
        )
        WHERE sku IN (
            SELECT DISTINCT sku FROM inventory_events WHERE change > 0
        )
    """)
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
