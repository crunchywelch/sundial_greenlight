#!/usr/bin/env python3
"""
Migrate cable SKUs to new pattern codes.

This script updates the database to match the new patterns.yaml definitions:
- BG (Black/Gold) → GL (Goldline)
- W (White) → PW (Pearl White)
- Removes EH (Electric Houndstooth) SKUs

Usage:
    python util/migrate_patterns.py           # Preview mode
    python util/migrate_patterns.py --apply   # Apply changes
"""

import sys
import argparse
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from greenlight.db import pg_pool


# Pattern code mappings (old_code -> new_code)
PATTERN_MIGRATIONS = {
    'BG': 'GL',   # Black/Gold -> Goldline
    'W': 'PW',    # White -> Pearl White
}

# Pattern name mappings
PATTERN_NAME_MIGRATIONS = {
    'Black/Gold': 'Goldline',
    'White': 'Pearl White',
}

# Patterns to remove
PATTERNS_TO_REMOVE = ['EH']  # Electric Houndstooth


def get_all_skus():
    """Get all SKUs from database"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT sku, series, core_cable, braid_material,
                       color_pattern, length, connector_type, description
                FROM cable_skus
                ORDER BY sku
            """)

            skus = []
            for row in cur.fetchall():
                skus.append({
                    'sku': row[0],
                    'series': row[1],
                    'core_cable': row[2],
                    'braid_material': row[3],
                    'color_pattern': row[4],
                    'length': row[5],
                    'connector_type': row[6],
                    'description': row[7]
                })

            return skus
    except Exception as e:
        print(f"❌ Error fetching SKUs: {e}")
        return []
    finally:
        pg_pool.putconn(conn)


def get_cables_for_sku(sku):
    """Get count of cables using this SKU"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM audio_cables WHERE sku = %s
            """, (sku,))
            return cur.fetchone()[0]
    except Exception as e:
        print(f"   ❌ Error checking cables for {sku}: {e}")
        return 0
    finally:
        pg_pool.putconn(conn)


def update_audio_cables_sku(old_sku, new_sku):
    """Update audio_cables records to use new SKU"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE audio_cables
                SET sku = %s
                WHERE sku = %s
            """, (new_sku, old_sku))
            affected = cur.rowcount
            conn.commit()
            return True, affected
    except Exception as e:
        print(f"   ❌ Error updating audio_cables for {old_sku}: {e}")
        conn.rollback()
        return False, 0
    finally:
        pg_pool.putconn(conn)


def insert_new_sku(sku_data):
    """Insert a new SKU record"""
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


def delete_old_sku(old_sku):
    """Delete an old SKU record (after cables have been migrated)"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM cable_skus WHERE sku = %s", (old_sku,))
            conn.commit()
            return True
    except Exception as e:
        print(f"   ❌ Error deleting {old_sku}: {e}")
        conn.rollback()
        return False
    finally:
        pg_pool.putconn(conn)


def delete_sku(sku):
    """Delete a SKU from the database"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM cable_skus WHERE sku = %s", (sku,))
            conn.commit()
            return True
    except Exception as e:
        print(f"   ❌ Error deleting {sku}: {e}")
        conn.rollback()
        return False
    finally:
        pg_pool.putconn(conn)


def replace_pattern_in_sku(sku_code, old_pattern, new_pattern):
    """Replace pattern code in SKU string"""
    # Pattern codes appear after the length and before connector suffix
    # Examples: SC-1BG, SC-3W-R, SP-1BG, TC-6RS

    # For simplicity, replace the old pattern code with new one
    if old_pattern in sku_code:
        return sku_code.replace(old_pattern, new_pattern)
    return sku_code


def update_description(old_desc, old_pattern_name, new_pattern_name):
    """Update description with new pattern name"""
    # Replace old pattern descriptions with new ones
    # Also simplify by removing product-line-specific prefixes

    desc = old_desc

    # Remove product line prefixes
    prefixes_to_remove = [
        'Studio-grade cable with ',
        'Studio patch cable with ',
        'Touring cable with ',
    ]

    for prefix in prefixes_to_remove:
        if desc.startswith(prefix):
            desc = desc[len(prefix):]
            break

    # Capitalize first letter after removing prefix
    if desc and desc[0].islower():
        desc = desc[0].upper() + desc[1:]

    return desc


def main():
    parser = argparse.ArgumentParser(
        description='Migrate cable SKUs to new pattern codes'
    )
    parser.add_argument('--apply', action='store_true',
                        help='Apply changes to database')
    args = parser.parse_args()

    print("🔄 Pattern Migration Tool")
    print("=" * 70)
    print()

    # Load all SKUs from database
    print("📊 Loading SKUs from database...")
    all_skus = get_all_skus()
    print(f"✅ Found {len(all_skus)} SKUs")
    print()

    # Categorize SKUs
    skus_to_update = []
    skus_to_delete = []

    for sku_data in all_skus:
        sku_code = sku_data['sku']
        color_pattern = sku_data['color_pattern']
        description = sku_data['description']

        # Check if this SKU needs pattern code migration
        needs_update = False
        new_sku_code = sku_code
        new_color_pattern = color_pattern
        new_description = description

        # Check for pattern code changes in SKU
        for old_code, new_code in PATTERN_MIGRATIONS.items():
            if old_code in sku_code:
                new_sku_code = replace_pattern_in_sku(sku_code, old_code, new_code)
                needs_update = True
                break

        # Check for pattern name changes
        for old_name, new_name in PATTERN_NAME_MIGRATIONS.items():
            if color_pattern == old_name:
                new_color_pattern = new_name
                new_description = update_description(description, old_name, new_name)
                needs_update = True
                break

        # Check if SKU should be deleted (removed pattern)
        should_delete = False
        for removed_pattern in PATTERNS_TO_REMOVE:
            if removed_pattern in sku_code:
                should_delete = True
                break

        if should_delete:
            skus_to_delete.append(sku_data)
        elif needs_update:
            skus_to_update.append({
                'old': sku_data,
                'new_sku': new_sku_code,
                'new_color_pattern': new_color_pattern,
                'new_description': new_description
            })

    # Show summary
    print("=" * 70)
    print(f"📊 Migration Summary:")
    print(f"   Total SKUs:        {len(all_skus)}")
    print(f"   To update:         {len(skus_to_update)}")
    print(f"   To delete:         {len(skus_to_delete)}")
    print(f"   No change:         {len(all_skus) - len(skus_to_update) - len(skus_to_delete)}")
    print("=" * 70)
    print()

    # Show SKUs to update
    if skus_to_update:
        print(f"📝 SKUs to update ({len(skus_to_update)}):")
        print()

        # Check if any have registered cables
        skus_with_cables = 0
        for item in skus_to_update:
            old = item['old']
            cable_count = get_cables_for_sku(old['sku'])
            cable_note = f" ({cable_count} cables)" if cable_count > 0 else ""
            if cable_count > 0:
                skus_with_cables += 1

            print(f"   {old['sku']:20} → {item['new_sku']}{cable_note}")
            print(f"      Color:  {old['color_pattern']:20} → {item['new_color_pattern']}")
            if old['description'] != item['new_description']:
                print(f"      Desc:   {old['description']}")
                print(f"           → {item['new_description']}")

        if skus_with_cables > 0:
            print()
            print(f"   ℹ️  {skus_with_cables} SKUs have registered cables (will be updated)")
        print()

    # Show SKUs to delete
    if skus_to_delete:
        print(f"🗑️  SKUs to delete ({len(skus_to_delete)}):")
        print()

        # Check if any have registered cables
        skus_with_cables = []
        for sku_data in skus_to_delete:
            cable_count = get_cables_for_sku(sku_data['sku'])
            cable_note = f" ({cable_count} cables - CANNOT DELETE)" if cable_count > 0 else ""
            if cable_count > 0:
                skus_with_cables.append((sku_data['sku'], cable_count))

            print(f"   {sku_data['sku']:20} | {sku_data['series']:20} | {sku_data['color_pattern']}{cable_note}")

        if skus_with_cables:
            print()
            print(f"   ⚠️  WARNING: {len(skus_with_cables)} SKUs have registered cables and CANNOT be deleted!")
            print(f"   You must reassign or delete those cables before deleting these SKUs.")
        print()

    if not skus_to_update and not skus_to_delete:
        print("✅ No migrations needed. All SKUs are up to date!")
        return 0

    # Apply changes if requested
    if args.apply:
        print("💾 Applying changes to database...")
        print()

        inserted = 0
        deleted = 0
        failed = 0
        cables_updated = 0

        # Step 1: Insert new SKU records
        if skus_to_update:
            print("Step 1: Inserting new SKU records...")
            for item in skus_to_update:
                old = item['old']
                new_sku_data = {
                    'sku': item['new_sku'],
                    'series': old['series'],
                    'core_cable': old['core_cable'],
                    'braid_material': old['braid_material'],
                    'color_pattern': item['new_color_pattern'],
                    'length': old['length'],
                    'connector_type': old['connector_type'],
                    'description': item['new_description']
                }

                if insert_new_sku(new_sku_data):
                    print(f"   ✅ Inserted: {item['new_sku']}")
                    inserted += 1
                else:
                    failed += 1
            print()

        # Step 2: Update audio_cables references
        if skus_to_update:
            print("Step 2: Updating audio_cables references...")
            for item in skus_to_update:
                old_sku = item['old']['sku']
                new_sku = item['new_sku']

                # Check if there are any cables using this SKU
                cable_count = get_cables_for_sku(old_sku)
                if cable_count > 0:
                    success, affected = update_audio_cables_sku(old_sku, new_sku)
                    if success:
                        print(f"   ✅ Updated {affected} cables: {old_sku} → {new_sku}")
                        cables_updated += affected
                    else:
                        print(f"   ⚠️  Failed to update cables for {old_sku}")
                        failed += 1
            print()

        # Step 3: Delete old SKU records
        if skus_to_update:
            print("Step 3: Deleting old SKU records...")
            for item in skus_to_update:
                old_sku = item['old']['sku']
                if delete_old_sku(old_sku):
                    print(f"   ✅ Deleted: {old_sku}")
                    deleted += 1
                else:
                    failed += 1
            print()

        # Step 4: Check for cables using SKUs to be deleted
        if skus_to_delete:
            print("Step 4: Checking for cables using obsolete SKUs...")
            skus_with_cables = []
            for sku_data in skus_to_delete:
                cable_count = get_cables_for_sku(sku_data['sku'])
                if cable_count > 0:
                    skus_with_cables.append((sku_data, cable_count))
                    print(f"   ⚠️  {sku_data['sku']} has {cable_count} cables")

            if skus_with_cables:
                print()
                print("   ⚠️  Cannot delete SKUs that have registered cables!")
                print("   Please reassign or delete those cables first.")
                print()
            else:
                print("   ✅ No cables found using obsolete SKUs")
                print()

        # Step 5: Delete obsolete SKUs (only if no cables reference them)
        if skus_to_delete:
            print("Step 5: Deleting obsolete SKUs...")
            obsolete_deleted = 0
            for sku_data in skus_to_delete:
                cable_count = get_cables_for_sku(sku_data['sku'])
                if cable_count > 0:
                    print(f"   ⚠️  Skipped (has cables): {sku_data['sku']}")
                    continue

                if delete_sku(sku_data['sku']):
                    print(f"   ✅ Deleted: {sku_data['sku']}")
                    obsolete_deleted += 1
                else:
                    failed += 1
            print()

        print("=" * 70)
        print(f"✅ Migration complete!")
        print(f"   New SKUs inserted:      {inserted}")
        print(f"   Old SKUs deleted:       {deleted}")
        print(f"   Obsolete SKUs deleted:  {obsolete_deleted}")
        print(f"   Cables updated:         {cables_updated}")
        print(f"   Failed:                 {failed}")
        print("=" * 70)
    else:
        print("ℹ️  This is a preview. Run with --apply to update the database.")
        print(f"   Command: python util/migrate_patterns.py --apply")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
