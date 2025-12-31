#!/usr/bin/env python3
"""
ONE-TIME SCRIPT: Remove length prefix from MISC cable descriptions

Since we now store length in audio_cables.length, we don't need it in the description.
This script removes the "Xft " prefix from descriptions.

Examples:
  "6ft dark putty houndstooth..." -> "dark putty houndstooth..."
  "4.5ft this oddball has..." -> "this oddball has..."

This is a temporary cleanup script and should only be run once.
"""

import sys
import re
sys.path.insert(0, '/home/welch/projects/sundial_greenlight')

from greenlight.db import pg_pool

def remove_length_prefix(description):
    """Remove length prefix from description like '6ft dark putty...'

    Returns:
        str: The cleaned description, or original if no prefix found
    """
    if not description:
        return description

    # Match number followed by 'ft' or '\'' at the start, then remove it
    # Handles: "6ft ", "4.5ft ", "5' " etc
    match = re.match(r'^(\d+(?:\.\d+)?)\s*(?:ft|\')\s+(.+)$', description, re.IGNORECASE)
    if match:
        return match.group(2)  # Return everything after the length prefix

    return description

def cleanup_misc_descriptions(dry_run=True):
    """Remove length prefix from MISC cable descriptions

    Args:
        dry_run: If True, show what would be updated without making changes
    """
    conn = pg_pool.getconn()

    try:
        with conn.cursor() as cur:
            # Find all MISC cables with descriptions
            cur.execute("""
                SELECT serial_number, sku, description
                FROM audio_cables
                WHERE sku LIKE '%-MISC'
                  AND description IS NOT NULL
                  AND description != ''
                ORDER BY serial_number
            """)

            misc_cables = cur.fetchall()

            if not misc_cables:
                print("No MISC cables with descriptions found")
                return

            print("=" * 80)
            print(f"Found {len(misc_cables)} MISC cable(s) with descriptions")
            print("=" * 80)

            updates = []
            skipped = []

            for serial, sku, description in misc_cables:
                cleaned = remove_length_prefix(description)

                print(f"\nSerial: {serial}")
                print(f"  SKU: {sku}")
                print(f"  Current: {description}")

                if cleaned != description:
                    print(f"  Cleaned: {cleaned}")
                    print(f"  ➜ Will update")
                    updates.append((cleaned, serial))
                else:
                    print(f"  ⚠️  SKIP: No length prefix found")
                    skipped.append(serial)

            print("\n" + "=" * 80)
            print("SUMMARY")
            print("=" * 80)
            print(f"Total MISC cables: {len(misc_cables)}")
            print(f"Will update: {len(updates)}")
            print(f"Will skip: {len(skipped)}")

            if not updates:
                print("\n✅ No updates needed - descriptions already clean")
                return

            if dry_run:
                print("\n" + "=" * 80)
                print("DRY RUN MODE - No changes made to database")
                print("=" * 80)
                print("\nTo apply these changes, run:")
                print("  python cleanup_misc_descriptions.py --apply")
            else:
                # Apply updates
                print("\n" + "=" * 80)
                print("APPLYING UPDATES")
                print("=" * 80)

                for cleaned_desc, serial in updates:
                    cur.execute("""
                        UPDATE audio_cables
                        SET description = %s
                        WHERE serial_number = %s
                    """, (cleaned_desc, serial))
                    print(f"✅ Updated {serial}")

                conn.commit()

                print("\n" + "=" * 80)
                print("✅ CLEANUP COMPLETE!")
                print("=" * 80)
                print(f"Updated {len(updates)} MISC cable description(s)")

                # Verify updates
                print("\n" + "=" * 80)
                print("VERIFICATION - Sample of updated cables:")
                print("=" * 80)

                for cleaned_desc, serial in updates[:5]:  # Show first 5
                    cur.execute("""
                        SELECT serial_number, sku, description
                        FROM audio_cables
                        WHERE serial_number = %s
                    """, (serial,))
                    result = cur.fetchone()
                    if result:
                        s, sku, desc = result
                        print(f"\n{s} ({sku}):")
                        print(f"  {desc}")

                if len(updates) > 5:
                    print(f"\n... and {len(updates) - 5} more")

    except Exception as e:
        print(f"\n❌ Error during cleanup: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        raise

    finally:
        pg_pool.putconn(conn)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Clean up MISC cable descriptions by removing length prefix")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes to database (default is dry-run)"
    )

    args = parser.parse_args()

    if args.apply:
        response = input("\n⚠️  This will UPDATE the database. Continue? (yes/no): ").strip().lower()
        if response != 'yes':
            print("Aborted.")
            sys.exit(0)

    cleanup_misc_descriptions(dry_run=not args.apply)
