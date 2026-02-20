#!/usr/bin/env python3
"""
ONE-TIME MIGRATION SCRIPT: Complete MISC cable data migration

This script performs both operations needed to migrate MISC cables to the new format:
1. Backfill length values from descriptions into audio_cables.length
2. Clean up descriptions by removing the length prefix

Example transformation:
  Before:
    - length: NULL
    - description: "6ft dark putty houndstooth with gold connectors"

  After:
    - length: 6.0
    - description: "dark putty houndstooth with gold connectors"

This should only be run once.
"""

import sys
import re
sys.path.insert(0, '/home/welch/projects/sundial_greenlight')

from greenlight.db import pg_pool

def extract_length_from_description(description):
    """Extract length from description like '6ft dark putty...'"""
    if not description:
        return None

    match = re.match(r'^(\d+(?:\.\d+)?)\s*ft\s+', description)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None

def remove_length_prefix(description):
    """Remove length prefix from description like '6ft dark putty...'"""
    if not description:
        return description

    match = re.match(r'^(\d+(?:\.\d+)?)\s*(?:ft|\')\s+(.+)$', description, re.IGNORECASE)
    if match:
        return match.group(2)

    return description

def migrate_misc_cables(dry_run=True):
    """Perform complete MISC cable migration"""
    conn = pg_pool.getconn()

    try:
        with conn.cursor() as cur:
            # Get all MISC cables
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
            print(f"MISC Cable Migration - Found {len(misc_cables)} cable(s)")
            print("=" * 80)

            updates = []

            for serial, sku, description, current_length in misc_cables:
                # Extract length from description
                extracted_length = extract_length_from_description(description)

                # Clean description
                cleaned_desc = remove_length_prefix(description)

                # Determine what needs updating
                needs_length = extracted_length is not None and (current_length is None or current_length == 0)
                needs_desc_cleanup = cleaned_desc != description

                if needs_length or needs_desc_cleanup:
                    new_length = extracted_length if needs_length else current_length
                    new_desc = cleaned_desc if needs_desc_cleanup else description

                    updates.append({
                        'serial': serial,
                        'sku': sku,
                        'old_length': current_length,
                        'new_length': new_length,
                        'old_desc': description,
                        'new_desc': new_desc,
                        'needs_length': needs_length,
                        'needs_desc': needs_desc_cleanup
                    })

                    print(f"\n{serial} ({sku}):")
                    if needs_length:
                        print(f"  Length: {current_length} → {new_length}")
                    if needs_desc_cleanup:
                        print(f"  Description:")
                        print(f"    Before: {description}")
                        print(f"    After:  {new_desc}")

            print("\n" + "=" * 80)
            print("SUMMARY")
            print("=" * 80)
            print(f"Total MISC cables: {len(misc_cables)}")
            print(f"Cables to update: {len(updates)}")
            print(f"  - Length updates: {sum(1 for u in updates if u['needs_length'])}")
            print(f"  - Description cleanups: {sum(1 for u in updates if u['needs_desc'])}")
            print(f"No changes needed: {len(misc_cables) - len(updates)}")

            if not updates:
                print("\n✅ All MISC cables are already migrated - no updates needed!")
                return

            if dry_run:
                print("\n" + "=" * 80)
                print("DRY RUN MODE - No changes made to database")
                print("=" * 80)
                print("\nTo apply these changes, run:")
                print("  python migrate_misc_cables.py --apply")
            else:
                # Apply updates
                print("\n" + "=" * 80)
                print("APPLYING UPDATES")
                print("=" * 80)

                for update in updates:
                    cur.execute("""
                        UPDATE audio_cables
                        SET length = %s,
                            description = %s
                        WHERE serial_number = %s
                    """, (update['new_length'], update['new_desc'], update['serial']))

                    print(f"✅ Updated {update['serial']}")

                conn.commit()

                print("\n" + "=" * 80)
                print("✅ MIGRATION COMPLETE!")
                print("=" * 80)
                print(f"Updated {len(updates)} MISC cable(s)")

                # Verify updates
                print("\n" + "=" * 80)
                print("VERIFICATION - All migrated cables:")
                print("=" * 80)

                cur.execute("""
                    SELECT serial_number, sku, length, description
                    FROM audio_cables
                    WHERE sku LIKE '%-MISC'
                    ORDER BY serial_number
                """)

                migrated = cur.fetchall()
                for serial, sku, length, desc in migrated:
                    print(f"\n{serial} ({sku}):")
                    print(f"  Length: {length} ft")
                    print(f"  Description: {desc}")

    except Exception as e:
        print(f"\n❌ Error during migration: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        raise

    finally:
        pg_pool.putconn(conn)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migrate MISC cables to new length + description format")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes to database (default is dry-run)"
    )

    args = parser.parse_args()

    if args.apply:
        print("\n" + "=" * 80)
        print("⚠️  MISC CABLE MIGRATION")
        print("=" * 80)
        print("\nThis will:")
        print("  1. Extract lengths from descriptions → audio_cables.length")
        print("  2. Remove length prefix from descriptions")
        print("\nThis is a ONE-TIME migration that modifies the database.")
        print("=" * 80)
        response = input("\nContinue? (yes/no): ").strip().lower()
        if response != 'yes':
            print("Aborted.")
            sys.exit(0)

    migrate_misc_cables(dry_run=not args.apply)
