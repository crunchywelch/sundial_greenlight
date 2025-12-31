#!/usr/bin/env python3
"""
Add miscellaneous SKUs and description field to audio_cables table.

This script:
1. Adds a 'description' column to audio_cables table (nullable)
2. Inserts MISC SKUs for each product line series
3. These SKUs are used for one-off and oddball cables that don't fit standard definitions

Usage:
    python util/add_misc_skus.py           # Preview mode
    python util/add_misc_skus.py --apply   # Apply changes
"""

import sys
import argparse
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from greenlight.db import pg_pool


# Miscellaneous SKUs to create
MISC_SKUS = [
    {
        'sku': 'SC-MISC',
        'series': 'Studio Classic',
        'core_cable': 'Varies',
        'braid_material': 'Rayon',
        'color_pattern': 'Miscellaneous',
        'length': '0',
        'connector_type': 'Varies',
        'description': 'Miscellaneous Studio Classic cable - see individual cable description'
    },
    {
        'sku': 'SP-MISC',
        'series': 'Studio Patch',
        'core_cable': 'Varies',
        'braid_material': 'Rayon',
        'color_pattern': 'Miscellaneous',
        'length': '0',
        'connector_type': 'Varies',
        'description': 'Miscellaneous Studio Patch cable - see individual cable description'
    },
    {
        'sku': 'SV-MISC',
        'series': 'Studio Vocal Classic',
        'core_cable': 'Varies',
        'braid_material': 'Rayon',
        'color_pattern': 'Miscellaneous',
        'length': '0',
        'connector_type': 'Varies',
        'description': 'Miscellaneous Studio Vocal cable - see individual cable description'
    },
    {
        'sku': 'TC-MISC',
        'series': 'Tour Classic',
        'core_cable': 'Varies',
        'braid_material': 'Cotton',
        'color_pattern': 'Miscellaneous',
        'length': '0',
        'connector_type': 'Varies',
        'description': 'Miscellaneous Tour Classic cable - see individual cable description'
    },
    {
        'sku': 'TV-MISC',
        'series': 'Tour Vocal Classic',
        'core_cable': 'Varies',
        'braid_material': 'Cotton',
        'color_pattern': 'Miscellaneous',
        'length': '0',
        'connector_type': 'Varies',
        'description': 'Miscellaneous Tour Vocal cable - see individual cable description'
    },
]


def check_description_column_exists():
    """Check if description column exists in audio_cables table"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'audio_cables'
                AND column_name = 'description'
            """)
            return cur.fetchone() is not None
    except Exception as e:
        print(f"❌ Error checking column: {e}")
        return False
    finally:
        pg_pool.putconn(conn)


def add_description_column():
    """Add description column to audio_cables table"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                ALTER TABLE audio_cables
                ADD COLUMN description TEXT
            """)
            conn.commit()
            return True
    except Exception as e:
        print(f"❌ Error adding column: {e}")
        conn.rollback()
        return False
    finally:
        pg_pool.putconn(conn)


def check_sku_exists(sku):
    """Check if a SKU already exists"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT sku FROM cable_skus WHERE sku = %s", (sku,))
            return cur.fetchone() is not None
    except Exception as e:
        print(f"❌ Error checking SKU: {e}")
        return False
    finally:
        pg_pool.putconn(conn)


def insert_misc_sku(sku_data):
    """Insert a miscellaneous SKU"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO cable_skus
                    (sku, series, core_cable, braid_material,
                     color_pattern, length, connector_type, description)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (sku_data['sku'], sku_data['series'],
                  sku_data['core_cable'], sku_data['braid_material'],
                  sku_data['color_pattern'], sku_data['length'],
                  sku_data['connector_type'], sku_data['description']))
            conn.commit()
            return True
    except Exception as e:
        print(f"   ❌ Error inserting {sku_data['sku']}: {e}")
        conn.rollback()
        return False
    finally:
        pg_pool.putconn(conn)


def main():
    parser = argparse.ArgumentParser(
        description='Add miscellaneous SKUs and description field'
    )
    parser.add_argument('--apply', action='store_true',
                        help='Apply changes to database')
    args = parser.parse_args()

    print("🔄 Miscellaneous SKU Setup")
    print("=" * 70)
    print()

    # Check if description column exists
    print("📊 Checking audio_cables table structure...")
    column_exists = check_description_column_exists()

    if column_exists:
        print("✅ Description column already exists in audio_cables table")
    else:
        print("⚠️  Description column does NOT exist in audio_cables table")
    print()

    # Check which MISC SKUs already exist
    print("🔍 Checking for existing MISC SKUs...")
    skus_to_insert = []
    skus_existing = []

    for sku_data in MISC_SKUS:
        if check_sku_exists(sku_data['sku']):
            skus_existing.append(sku_data['sku'])
        else:
            skus_to_insert.append(sku_data)

    print(f"✅ Found {len(skus_existing)} existing MISC SKUs")
    print(f"📝 Need to insert {len(skus_to_insert)} MISC SKUs")
    print()

    # Show summary
    print("=" * 70)
    print("📊 Summary:")
    print(f"   Description column exists: {'Yes' if column_exists else 'No (will add)'}")
    print(f"   Existing MISC SKUs:        {len(skus_existing)}")
    print(f"   New MISC SKUs to insert:   {len(skus_to_insert)}")
    print("=" * 70)
    print()

    # Show existing MISC SKUs
    if skus_existing:
        print(f"✅ Existing MISC SKUs:")
        for sku in skus_existing:
            print(f"   {sku}")
        print()

    # Show MISC SKUs to insert
    if skus_to_insert:
        print(f"📋 MISC SKUs to insert:")
        for sku_data in skus_to_insert:
            print(f"   {sku_data['sku']:15} | {sku_data['series']:25} | {sku_data['braid_material']}")
        print()

    if not column_exists or skus_to_insert:
        # Apply changes if requested
        if args.apply:
            print("💾 Applying changes to database...")
            print()

            # Add description column if needed
            if not column_exists:
                print("Adding description column to audio_cables table...")
                if add_description_column():
                    print("   ✅ Added description column to audio_cables")
                else:
                    print("   ❌ Failed to add description column")
                    return 1
                print()

            # Insert MISC SKUs
            if skus_to_insert:
                print("Inserting MISC SKUs...")
                inserted = 0
                failed = 0

                for sku_data in skus_to_insert:
                    if insert_misc_sku(sku_data):
                        print(f"   ✅ Inserted: {sku_data['sku']}")
                        inserted += 1
                    else:
                        failed += 1

                print()
                print("=" * 70)
                print(f"✅ Setup complete!")
                print(f"   MISC SKUs inserted: {inserted}")
                print(f"   Failed:             {failed}")
                print("=" * 70)
        else:
            print("ℹ️  This is a preview. Run with --apply to make changes.")
            print(f"   Command: python util/add_misc_skus.py --apply")
    else:
        print("✅ All setup already complete. Nothing to do!")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
