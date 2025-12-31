#!/usr/bin/env python3
"""
ONE-TIME SCRIPT: Backfill length values for existing MISC cables

This script extracts length from MISC cable descriptions (e.g., "6ft dark putty...")
and populates the audio_cables.length column.

This is a temporary migration script and should only be run once.
"""

import sys
import re
sys.path.insert(0, '/home/welch/projects/sundial_greenlight')

from greenlight.db import pg_pool

def extract_length_from_description(description):
    """Extract length from description like '6ft dark putty...'

    Returns:
        float: The extracted length, or None if not found
    """
    if not description:
        return None

    # Match number followed by 'ft' at the start of the description
    match = re.match(r'^(\d+(?:\.\d+)?)\s*ft\s+', description)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None

def backfill_misc_lengths(dry_run=True):
    """Backfill length values for MISC cables from their descriptions

    Args:
        dry_run: If True, show what would be updated without making changes
    """
    conn = pg_pool.getconn()

    try:
        with conn.cursor() as cur:
            # Find all MISC cables with descriptions but no length set
            cur.execute("""
                SELECT serial_number, sku, description, length
                FROM audio_cables
                WHERE sku LIKE '%-MISC'
                ORDER BY serial_number
            """)

            misc_cables = cur.fetchall()

            if not misc_cables:
                print("No MISC cables found in database")
                return

            print("=" * 80)
            print(f"Found {len(misc_cables)} MISC cable(s)")
            print("=" * 80)

            updates = []
            skipped = []

            for serial, sku, description, current_length in misc_cables:
                extracted_length = extract_length_from_description(description)

                print(f"\nSerial: {serial}")
                print(f"  SKU: {sku}")
                print(f"  Current length: {current_length}")
                print(f"  Description: {description}")
                print(f"  Extracted length: {extracted_length}")

                # Only update if:
                # 1. We successfully extracted a length
                # 2. Current length is None or 0
                if extracted_length is not None and (current_length is None or current_length == 0):
                    updates.append((extracted_length, serial))
                    print(f"  ➜ Will update to: {extracted_length} ft")
                elif extracted_length is None:
                    skipped.append((serial, "Could not extract length from description"))
                    print(f"  ⚠️  SKIP: Could not extract length from description")
                elif current_length and current_length != 0:
                    skipped.append((serial, f"Already has length: {current_length}"))
                    print(f"  ⚠️  SKIP: Already has length set")

            print("\n" + "=" * 80)
            print("SUMMARY")
            print("=" * 80)
            print(f"Total MISC cables: {len(misc_cables)}")
            print(f"Will update: {len(updates)}")
            print(f"Will skip: {len(skipped)}")

            if skipped:
                print("\nSkipped cables:")
                for serial, reason in skipped:
                    print(f"  - {serial}: {reason}")

            if not updates:
                print("\n✅ No updates needed - all MISC cables already have lengths set")
                return

            if dry_run:
                print("\n" + "=" * 80)
                print("DRY RUN MODE - No changes made to database")
                print("=" * 80)
                print("\nTo apply these changes, run:")
                print("  python backfill_misc_lengths.py --apply")
            else:
                # Apply updates
                print("\n" + "=" * 80)
                print("APPLYING UPDATES")
                print("=" * 80)

                for length, serial in updates:
                    cur.execute("""
                        UPDATE audio_cables
                        SET length = %s
                        WHERE serial_number = %s
                    """, (length, serial))
                    print(f"✅ Updated {serial} -> {length} ft")

                conn.commit()

                print("\n" + "=" * 80)
                print("✅ BACKFILL COMPLETE!")
                print("=" * 80)
                print(f"Updated {len(updates)} MISC cable(s) with extracted lengths")

                # Verify updates
                print("\n" + "=" * 80)
                print("VERIFICATION")
                print("=" * 80)

                for length, serial in updates:
                    cur.execute("""
                        SELECT serial_number, sku, length, description
                        FROM audio_cables
                        WHERE serial_number = %s
                    """, (serial,))
                    result = cur.fetchone()
                    if result:
                        s, sku, l, desc = result
                        print(f"\n{s} ({sku}):")
                        print(f"  Length: {l} ft")
                        print(f"  Description: {desc}")

    except Exception as e:
        print(f"\n❌ Error during backfill: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        raise

    finally:
        pg_pool.putconn(conn)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Backfill MISC cable lengths from descriptions")
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

    backfill_misc_lengths(dry_run=not args.apply)
