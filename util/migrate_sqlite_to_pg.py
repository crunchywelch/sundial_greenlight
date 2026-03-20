#!/usr/bin/env python3
"""
Migrate data from SQLite sundial.db to PostgreSQL valuation schema.

Copies all tables from the SQLite database into the PostgreSQL valuation
schema. Safe to re-run — uses ON CONFLICT DO NOTHING to skip existing rows.

Usage:
    python util/migrate_sqlite_to_pg.py
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from util.wire.sundial_wire_db import get_db, init_db

SQLITE_PATH = Path(__file__).parent.parent / "data" / "sundial.db"

TABLES = [
    "products",
    "vendor_parts",
    "inventory_snapshots",
    "wire_cost_params",
    "wire_materials",
]


def main():
    if not SQLITE_PATH.exists():
        print(f"SQLite database not found: {SQLITE_PATH}")
        return 1

    # Open SQLite source
    sqlite_conn = sqlite3.connect(str(SQLITE_PATH))
    sqlite_conn.row_factory = sqlite3.Row

    # Open PostgreSQL target and create schema/tables
    pg = get_db()
    init_db(pg)

    for table in TABLES:
        # Check if table exists in SQLite
        exists = sqlite_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,)
        ).fetchone()
        if not exists:
            print(f"  {table}: not in SQLite, skipping")
            continue

        rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
        if not rows:
            print(f"  {table}: empty")
            continue

        columns = rows[0].keys()
        col_list = ", ".join(columns)
        val_list = ", ".join(f"%({c})s" for c in columns)
        sql = f"INSERT INTO {table} ({col_list}) VALUES ({val_list}) ON CONFLICT DO NOTHING"

        row_dicts = [dict(r) for r in rows]
        pg.executemany(sql, row_dicts)
        pg.commit()

        # Verify count
        count = pg.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {len(rows)} SQLite rows -> {count} PostgreSQL rows")

    sqlite_conn.close()
    pg.close()

    print()
    print("Migration complete!")
    print("You can now remove data/sundial.db from git tracking:")
    print("  git rm --cached data/sundial.db")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
