#!/usr/bin/env python3
"""
PostgreSQL database layer for Sundial store data.

Stores product data and inventory snapshots from both Shopify stores
(wire + audio) in the Greenlight PostgreSQL database.

Usage:
    from util.wire.sundial_wire_db import get_db, init_db, upsert_products

    db = get_db()
    init_db(db)
    upsert_products(db, rows)
"""

import csv
from pathlib import Path

import psycopg2
import psycopg2.extras

DATA_DIR = Path(__file__).parent.parent.parent / "data"


class PgConnection:
    """Wraps psycopg2 connection to provide sqlite3-compatible execute() API.

    Allows calling code to use conn.execute(sql, params).fetchall() without
    manually managing cursors. Uses DictCursor so rows support both integer
    indexing (row[0]) and column name access (row["sku"]).
    """

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(sql, params)
        return cur

    def executemany(self, sql, params_seq):
        cur = self._conn.cursor()
        cur.executemany(sql, params_seq)
        return cur

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_db(path=None):
    """Return a PgConnection to the valuation schema.

    The path parameter is accepted for backward compatibility but ignored.
    Reads PostgreSQL credentials directly from environment / .env file
    so callers don't need greenlight.config on their import path.
    """
    import os
    from dotenv import load_dotenv

    env_path = Path(__file__).parent.parent.parent / ".env"
    load_dotenv(env_path)

    db_config = {
        "dbname": os.getenv("GREENLIGHT_DB_NAME"),
        "user": os.getenv("GREENLIGHT_DB_USER"),
        "password": os.getenv("GREENLIGHT_DB_PASS"),
        "host": os.getenv("GREENLIGHT_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("GREENLIGHT_DB_PORT", 5432)),
        "sslmode": os.getenv("GREENLIGHT_DB_SSLMODE", "require"),
    }

    conn = psycopg2.connect(**db_config)
    return PgConnection(conn)


def init_db(conn=None):
    """Create the valuation schema and all tables if they don't exist."""
    close = False
    if conn is None:
        conn = get_db()
        close = True

    conn.execute("""
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
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vendor_parts (
            sku TEXT,
            vendor TEXT,
            part_number TEXT,
            PRIMARY KEY (sku, vendor)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS inventory_snapshots (
            sku TEXT,
            snapshot_date TEXT,
            qty INTEGER,
            cost REAL,
            source TEXT,
            PRIMARY KEY (sku, snapshot_date)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wire_cost_params (
            key TEXT PRIMARY KEY,
            category TEXT,
            value REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wire_materials (
            material_sku TEXT,
            description TEXT,
            wire_cost_key TEXT,
            product_family TEXT,
            PRIMARY KEY (material_sku, product_family)
        )
    """)
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
           VALUES (%(sku)s, %(handle)s, %(title)s, %(option)s,
                   %(product_type)s, %(qty)s, %(price)s, %(is_wire)s,
                   %(cost)s, %(cost_vendor)s, %(cost_notes)s, CURRENT_TIMESTAMP)
           ON CONFLICT(sku) DO UPDATE SET
               handle=EXCLUDED.handle, title=EXCLUDED.title,
               option=EXCLUDED.option, product_type=EXCLUDED.product_type,
               qty=EXCLUDED.qty, price=EXCLUDED.price,
               is_wire=EXCLUDED.is_wire,
               cost=COALESCE(EXCLUDED.cost, products.cost),
               cost_vendor=COALESCE(EXCLUDED.cost_vendor, products.cost_vendor),
               cost_notes=COALESCE(EXCLUDED.cost_notes, products.cost_notes),
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
           VALUES (%(sku)s, %(vendor)s, %(part_number)s)
           ON CONFLICT(sku, vendor) DO UPDATE SET
               part_number=EXCLUDED.part_number""",
        rows,
    )
    conn.commit()


def upsert_inventory_snapshot(conn, sku, snapshot_date, qty, cost, source):
    """Insert or update a single inventory snapshot."""
    conn.execute(
        """INSERT INTO inventory_snapshots (sku, snapshot_date, qty, cost, source)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT(sku, snapshot_date) DO UPDATE SET
               qty=EXCLUDED.qty, cost=EXCLUDED.cost, source=EXCLUDED.source""",
        (sku, snapshot_date, qty, cost, source),
    )
    conn.commit()


def upsert_wire_cost_params(conn, rows):
    """Bulk insert/update wire cost params.

    Each row is a dict with keys: key, category, value.
    """
    conn.executemany(
        """INSERT INTO wire_cost_params (key, category, value)
           VALUES (%(key)s, %(category)s, %(value)s)
           ON CONFLICT(key) DO UPDATE SET
               category=EXCLUDED.category, value=EXCLUDED.value""",
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
           VALUES (%(material_sku)s, %(description)s, %(wire_cost_key)s, %(product_family)s)
           ON CONFLICT(material_sku, product_family) DO UPDATE SET
               description=EXCLUDED.description,
               wire_cost_key=EXCLUDED.wire_cost_key""",
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
    cursor = conn.execute(query, params)
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
