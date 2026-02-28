#!/usr/bin/env python3
"""
Pull all inventory adjustment events from Shopify and store in SQLite.

Queries ShopifyQL inventory_adjustment_history in weekly batches to stay
under the 1000-row query limit, and saves to the SQLite database.

This data can be used to back-calculate inventory levels at Dec 31, 2025
by subtracting net changes from current (corrected) inventory counts.

Usage:
    python util/pull_inventory_events.py            # Pull and store in DB
    python util/pull_inventory_events.py --export   # Also export CSV
"""

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

from sundial_wire_db import DATA_DIR, get_db, init_db, insert_inventory_events, update_last_received, export_csv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

EXPORT_CSV = DATA_DIR / "exports" / "inventory_events_2026.csv"

SHOP_URL = os.getenv("SHOPIFY_WIRE_SHOP_URL")
TOKEN = os.getenv("SHOPIFY_WIRE_ACCESS_TOKEN")
GRAPHQL_URL = f"https://{SHOP_URL}/admin/api/unstable/graphql.json"
HEADERS = {
    "X-Shopify-Access-Token": TOKEN,
    "Content-Type": "application/json",
}

# ShopifyQL columns to pull
COLUMNS = [
    "day",
    "product_variant_sku",
    "inventory_adjustment_change",
    "inventory_change_reason",
    "inventory_state",
    "staff_member_name",
]

SHOW_COLS = ", ".join(COLUMNS[2:3])  # the measure
GROUP_COLS = ", ".join([COLUMNS[0]] + COLUMNS[1:2] + COLUMNS[3:])  # dimensions


EARLIEST_START = date(2025, 8, 16)


def query_batch(since_days, until_days):
    """Query one batch of inventory events using relative day offsets."""
    shopifyql = (
        f"FROM inventory_adjustment_history "
        f"WHERE inventory_change_reason != 'purchase' "
        f"AND inventory_change_reason != 'order_fulfilled' "
        f"AND inventory_change_reason != 'order_edited' "
        f"AND inventory_change_reason != 'order_cancellation' "
        f"SHOW {SHOW_COLS} "
        f"GROUP BY {GROUP_COLS} "
        f"SINCE -{since_days}d "
    )
    if until_days > 0:
        shopifyql += f"UNTIL -{until_days}d "
    shopifyql += "ORDER BY day LIMIT 1000"

    graphql = (
        '{ shopifyqlQuery(query: "'
        + shopifyql
        + '") { parseErrors tableData { columns { name dataType } rows } } }'
    )

    resp = requests.post(GRAPHQL_URL, headers=HEADERS, json={"query": graphql})
    data = resp.json()

    if "errors" in data:
        errors = data["errors"]
        # Check for rate limiting
        if any("THROTTLED" in str(e) for e in errors):
            return "throttled", []
        print(f"  GraphQL errors: {errors}")
        return "error", []

    result = data["data"]["shopifyqlQuery"]
    if result.get("parseErrors"):
        print(f"  Parse errors: {result['parseErrors']}")
        return "error", []

    rows = result["tableData"]["rows"]
    return "ok", rows


def main():
    parser = argparse.ArgumentParser(
        description="Pull inventory events from Shopify into SQLite"
    )
    parser.add_argument(
        "--export", action="store_true",
        help="Also export CSV to data/exports/"
    )
    args = parser.parse_args()

    conn = get_db()
    init_db(conn)

    # Resume from the latest event in the DB
    latest_event = conn.execute(
        "SELECT MAX(event_date) FROM inventory_events"
    ).fetchone()[0]
    start = date.fromisoformat(latest_event) if latest_event else EARLIEST_START

    today = date.today()
    total_pulled = 0

    print("Pulling inventory adjustment events from Shopify...")
    print(f"Store: {SHOP_URL}")
    print(f"From:  {start}")
    print()

    # Pull in monthly batches, writing to DB after each
    batch_start = start
    while batch_start < today:
        batch_end = min(batch_start + timedelta(days=30), today)

        since_days = (today - batch_start).days
        until_days = (today - batch_end).days

        label = f"{batch_start} to {batch_end}"
        print(f"  {label}...", end=" ", flush=True)

        retries = 0
        while retries < 3:
            status, rows = query_batch(since_days, until_days)
            if status == "ok":
                break
            elif status == "throttled":
                retries += 1
                wait = 10 * retries
                print(f"throttled, waiting {wait}s...", end=" ", flush=True)
                time.sleep(wait)
            else:
                break

        if status != "ok":
            print(f"FAILED ({status})")
            batch_start = batch_end
            continue

        hit_limit = " ** HIT LIMIT **" if len(rows) >= 1000 else ""
        print(f"{len(rows)} events{hit_limit}")

        if len(rows) >= 1000:
            print(f"  WARNING: batch {label} hit 1000 row limit, data may be incomplete!")

        # Write batch to DB immediately so progress is saved
        if rows:
            keep_reasons = {"received", "correction", "initial_adjustment",
                            "manual_adjustment", "restock"}
            db_rows = []
            for row in rows:
                reason = row.get("inventory_change_reason", "")
                if reason not in keep_reasons:
                    continue
                change_str = row.get("inventory_adjustment_change", "")
                try:
                    change = int(float(change_str)) if change_str else 0
                except (ValueError, TypeError):
                    change = 0
                if change <= 0:
                    continue
                db_rows.append({
                    "event_date": (row.get("day") or "")[:10],
                    "sku": row.get("product_variant_sku", ""),
                    "change": change,
                    "reason": reason,
                    "state": row.get("inventory_state", ""),
                    "staff": row.get("staff_member_name", ""),
                })
            if db_rows:
                insert_inventory_events(conn, db_rows)
            total_pulled += len(db_rows)

        batch_start = batch_end
        # Delay to avoid rate limits
        time.sleep(4)

    print()
    print(f"Total events pulled: {total_pulled}")

    update_last_received(conn)

    total = conn.execute("SELECT COUNT(*) FROM inventory_events").fetchone()[0]
    print(f"Total events in database: {total}")

    # Export CSV if requested
    if args.export:
        n = export_csv(
            conn,
            "SELECT event_date AS date, sku, change, reason, state, staff "
            "FROM inventory_events ORDER BY event_date, sku",
            EXPORT_CSV,
        )
        print(f"Exported {n} events to {EXPORT_CSV}")

    # Quick summary
    skus = conn.execute(
        "SELECT COUNT(DISTINCT sku) FROM inventory_events WHERE sku != ''"
    ).fetchone()[0]
    print(f"Unique SKUs with events: {skus}")

    conn.close()
    print()
    print("Done!")


if __name__ == "__main__":
    sys.exit(main() or 0)
