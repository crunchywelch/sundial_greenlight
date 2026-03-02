#!/usr/bin/env python3
"""
Pull audio cable inventory events from PostgreSQL into SQLite.

Derives inventory events from the audio_cables table in PostgreSQL, where
each cable registration (updated_timestamp) represents a +1 inventory event
for that SKU on that date.

Usage:
    python util/audio/audio_pull_inventory_events.py            # Pull and store in DB
    python util/audio/audio_pull_inventory_events.py --export   # Also export CSV
"""

import argparse
import sys
from pathlib import Path

import psycopg2

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from greenlight.config import DB_CONFIG
from util.wire.sundial_wire_db import DATA_DIR, get_db, init_db, insert_inventory_events, update_last_received, export_csv

EXPORT_CSV = DATA_DIR / "exports" / "audio_inventory_events.csv"


def fetch_events_from_postgres(since_date=None):
    """Query PostgreSQL for audio cable registrations grouped by date and SKU.

    Each cable registration = +1 inventory received for that SKU on that day.

    Returns list of dicts ready for insert_inventory_events.
    """
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            query = """
                SELECT
                    DATE(updated_timestamp) AS event_date,
                    sku,
                    COUNT(*) AS change
                FROM audio_cables
                WHERE updated_timestamp IS NOT NULL
            """
            params = []
            if since_date:
                query += " AND DATE(updated_timestamp) >= %s"
                params.append(since_date)
            query += """
                GROUP BY DATE(updated_timestamp), sku
                ORDER BY DATE(updated_timestamp), sku
            """
            cur.execute(query, params)
            rows = []
            for event_date, sku, change in cur.fetchall():
                rows.append({
                    "event_date": event_date.isoformat(),
                    "sku": sku,
                    "change": change,
                    "reason": "registered",
                    "state": "available",
                    "staff": "",
                })
            return rows
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Pull audio cable inventory events from PostgreSQL into SQLite"
    )
    parser.add_argument(
        "--export", action="store_true",
        help="Also export CSV to data/exports/"
    )
    parser.add_argument(
        "--full", action="store_true",
        help="Full refresh (ignore existing events, re-pull all)"
    )
    args = parser.parse_args()

    sqlite_conn = get_db()
    init_db(sqlite_conn)

    # Resume from the latest audio event in SQLite unless --full
    since_date = None
    if not args.full:
        latest_event = sqlite_conn.execute(
            """SELECT MAX(event_date) FROM inventory_events
               WHERE sku LIKE 'SC-%' OR sku LIKE 'SV-%'
                  OR sku LIKE 'TC-%' OR sku LIKE 'TV-%'"""
        ).fetchone()[0]
        if latest_event:
            since_date = latest_event

    print("Pulling audio cable inventory events from PostgreSQL...")
    print(f"From:  {since_date or 'beginning'}")
    print()

    rows = fetch_events_from_postgres(since_date)
    print(f"  Fetched {len(rows)} events from PostgreSQL")

    if rows:
        insert_inventory_events(sqlite_conn, rows)
        print(f"  Inserted into SQLite (duplicates skipped)")

    update_last_received(sqlite_conn)

    # Count audio-specific events
    audio_total = sqlite_conn.execute(
        """SELECT COUNT(*) FROM inventory_events
           WHERE sku LIKE 'SC-%' OR sku LIKE 'SV-%'
              OR sku LIKE 'TC-%' OR sku LIKE 'TV-%'"""
    ).fetchone()[0]
    total = sqlite_conn.execute("SELECT COUNT(*) FROM inventory_events").fetchone()[0]
    print()
    print(f"  Audio events in database: {audio_total}")
    print(f"  Total events in database: {total}")

    # Export CSV if requested
    if args.export:
        n = export_csv(
            sqlite_conn,
            """SELECT event_date AS date, sku, change, reason, state, staff
               FROM inventory_events
               WHERE sku LIKE 'SC-%' OR sku LIKE 'SV-%'
                  OR sku LIKE 'TC-%' OR sku LIKE 'TV-%'
               ORDER BY event_date, sku""",
            EXPORT_CSV,
        )
        print(f"  Exported {n} events to {EXPORT_CSV}")

    # Quick summary
    skus = sqlite_conn.execute(
        """SELECT COUNT(DISTINCT sku) FROM inventory_events
           WHERE sku != ''
             AND (sku LIKE 'SC-%' OR sku LIKE 'SV-%'
               OR sku LIKE 'TC-%' OR sku LIKE 'TV-%')"""
    ).fetchone()[0]
    print(f"  Unique audio SKUs with events: {skus}")

    sqlite_conn.close()
    print()
    print("Done!")


if __name__ == "__main__":
    sys.exit(main() or 0)
