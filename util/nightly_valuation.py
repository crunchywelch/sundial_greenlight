#!/usr/bin/env python3
"""
Nightly inventory data refresh.

Refreshes product data from both Shopify stores (wire + audio) into
PostgreSQL, then prints a valuation summary.

Designed to run via systemd timer (nightly-valuation.timer).

Usage:
    python util/nightly_valuation.py                # Refresh and show report
    python util/nightly_valuation.py --skip-refresh # Report only (use existing data)
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from greenlight.log import setup_logging
setup_logging()

from util.wire.sundial_wire_db import get_db, init_db
from util.valuation_report import run_report, get_latest_date


def refresh_shopify_data(conn):
    """Refresh product data from both Shopify stores."""
    print("Refreshing wire store...")
    from util.wire.wire_refresh_products import refresh_from_shopify as wire_refresh
    wire_refresh(conn)

    print("Refreshing audio store...")
    from util.audio.audio_refresh_products import refresh_from_shopify as audio_refresh
    audio_refresh(conn)


def main():
    parser = argparse.ArgumentParser(
        description="Nightly inventory data refresh and valuation report"
    )
    parser.add_argument(
        "--skip-refresh", action="store_true",
        help="Skip Shopify refresh (use existing data)"
    )
    args = parser.parse_args()

    conn = get_db()
    init_db(conn)

    if not args.skip_refresh:
        refresh_shopify_data(conn)
    else:
        print("Skipping Shopify refresh (using cached data)")
    print()

    report_date = get_latest_date(conn)
    if report_date:
        run_report(conn, report_date)
    else:
        print("No snapshot data found.")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
