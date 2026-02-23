#!/usr/bin/env python3
"""
Sync cable SKUs from YAML product line definitions to PostgreSQL.

This script:
1. Reads all YAML files from product_lines/
2. Generates all SKU combinations from product lines and their colors
3. Compares with database
4. INSERTS missing SKUs and UPDATES existing SKU descriptions
5. Reports SKUs in database that don't match any YAML definition

Usage:
    python util/sync_skus.py           # Preview mode (show what would be changed)
    python util/sync_skus.py --apply   # Actually insert/update SKUs
"""

import sys
import yaml
import argparse
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from greenlight.db import pg_pool


def load_product_lines(product_lines_dir):
    """Load all YAML product line definitions (skip patterns.yaml)"""
    product_lines = []

    yaml_files = sorted(product_lines_dir.glob('*.yaml'))

    if not yaml_files:
        print(f"⚠️  Warning: No YAML files found in {product_lines_dir}")
        return []

    for yaml_file in yaml_files:
        # Skip patterns.yaml - it's not a product line definition
        if yaml_file.name == 'patterns.yaml':
            continue

        print(f"📖 Reading: {yaml_file.name}")
        with open(yaml_file, 'r') as f:
            product_line = yaml.safe_load(f)
            product_lines.append(product_line)

    return product_lines


def load_patterns(patterns_file):
    """Load pattern definitions from patterns.yaml"""
    if not patterns_file.exists():
        print(f"❌ Error: patterns.yaml not found at {patterns_file}")
        return []

    print(f"🎨 Reading: {patterns_file.name}")
    with open(patterns_file, 'r') as f:
        data = yaml.safe_load(f)
        patterns = data.get('patterns', [])

    print(f"   ✅ Loaded {len(patterns)} patterns")
    return patterns


def get_patterns_for_fabric_type(patterns, fabric_type):
    """Filter patterns by fabric type"""
    return [p for p in patterns if p['fabric_type'] == fabric_type.lower()]


def format_length_for_sku(length):
    """Format length for SKU (e.g., 0.5 -> '06', 3 -> '3', 10 -> '10')"""
    if length < 1:
        # For Studio Patch 0.5ft, use '06' to represent 6 inches
        return '06'
    else:
        return str(int(length))


def generate_sku_code(prefix, length, color_code, connector_code, include_color):
    """Generate SKU code from components"""
    length_str = format_length_for_sku(length)
    sku = f"{prefix}-{length_str}"
    
    # Add color code if this product line uses it
    if include_color:
        sku += color_code
    
    # Add connector suffix
    if connector_code:
        sku += connector_code
    
    return sku


def generate_skus(product_lines, patterns):
    """Generate all SKU combinations from product lines and patterns"""
    skus = []

    for product_line in product_lines:
        product_line_name = product_line['product_line']
        print(f"\n🔧 Processing: {product_line_name}")

        prefix = product_line['sku_prefix']
        core_cable = product_line['core_cable']
        braid_material = product_line['braid_material']
        include_color = product_line.get('include_color_in_sku', True)

        # Get patterns that match this product line's fabric type
        matching_patterns = get_patterns_for_fabric_type(patterns, braid_material)

        if not matching_patterns:
            print(f"   ⚠️  Warning: No patterns found for fabric type '{braid_material}'")
            continue

        print(f"   Found {len(matching_patterns)} patterns for {braid_material}")

        # Check if connectors are defined
        connectors = product_line.get('connectors', [])
        if not connectors:
            print(f"   ⚠️  Warning: No connectors defined for {product_line_name}, skipping")
            continue

        # Generate SKUs for each combination
        for length in product_line['lengths']:
            for pattern in matching_patterns:
                pattern_code = pattern['code']
                pattern_name = pattern['name']
                base_description = pattern['description']

                for connector in connectors:
                    connector_code = connector['code']
                    connector_display = connector['display']

                    # Generate SKU
                    sku = generate_sku_code(prefix, length, pattern_code,
                                           connector_code, include_color)

                    # Build description
                    description = base_description
                    if connector_code and '-R' in str(connector_code):
                        description += " and right angle plug"

                    skus.append({
                        'sku': sku,
                        'series': product_line_name,
                        'core_cable': core_cable,
                        'braid_material': braid_material,
                        'color_pattern': pattern_name,
                        'length': str(length),  # Store as string for database
                        'connector_type': connector_display,
                        'description': description
                    })

        print(f"   ✅ Generated {len([s for s in skus if s['series'] == product_line_name])} SKUs for {product_line_name}")

    return skus


def get_existing_skus():
    """Get all SKUs currently in database with their descriptions"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT sku, description, series, core_cable, braid_material,
                       color_pattern, length, connector_type
                FROM cable_skus
                ORDER BY sku
            """)

            existing = {}
            for row in cur.fetchall():
                existing[row[0]] = {
                    'sku': row[0],
                    'description': row[1],
                    'series': row[2],
                    'core_cable': row[3],
                    'braid_material': row[4],
                    'color_pattern': row[5],
                    'length': row[6],
                    'connector_type': row[7]
                }
            
            return existing
    except Exception as e:
        print(f"❌ Error fetching existing SKUs: {e}")
        return {}
    finally:
        pg_pool.putconn(conn)


def insert_sku(sku_data):
    """Insert a single SKU into database"""
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


def update_sku(sku_data):
    """Update an existing SKU in database"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE cable_skus
                SET description = %s,
                    series = %s,
                    core_cable = %s,
                    braid_material = %s,
                    color_pattern = %s,
                    length = %s,
                    connector_type = %s
                WHERE sku = %s
            """, (sku_data['description'], sku_data['series'],
                  sku_data['core_cable'], sku_data['braid_material'],
                  sku_data['color_pattern'], sku_data['length'],
                  sku_data['connector_type'], sku_data['sku']))
            conn.commit()
            return True
    except Exception as e:
        print(f"   ❌ Error updating {sku_data['sku']}: {e}")
        conn.rollback()
        return False
    finally:
        pg_pool.putconn(conn)


def main():
    parser = argparse.ArgumentParser(
        description='Sync cable SKUs from YAML definitions to PostgreSQL'
    )
    parser.add_argument('--apply', action='store_true',
                        help='Apply changes (insert/update SKUs)')
    args = parser.parse_args()
    
    # Paths
    script_dir = Path(__file__).parent
    product_lines_dir = script_dir / 'product_lines'
    patterns_file = product_lines_dir / 'patterns.yaml'

    print("🔄 Cable SKU Sync Tool")
    print("=" * 60)
    print()

    # Load patterns from patterns.yaml
    print("🎨 Loading patterns from patterns.yaml...")
    patterns = load_patterns(patterns_file)

    if not patterns:
        print("❌ No patterns found. Exiting.")
        return 1

    print(f"✅ Loaded {len(patterns)} patterns")
    print()

    # Load product line definitions
    print("📚 Loading product line definitions...")
    product_lines = load_product_lines(product_lines_dir)

    if not product_lines:
        print("❌ No product lines found. Exiting.")
        return 1

    print(f"✅ Loaded {len(product_lines)} product lines")
    print()

    # Generate all SKUs
    print("🔧 Generating SKU combinations...")
    generated_skus = generate_skus(product_lines, patterns)
    
    print()
    print(f"✅ Generated {len(generated_skus)} total SKUs")
    print()
    
    # Get existing SKUs from database
    print("🔍 Checking database for existing SKUs...")
    existing_skus = get_existing_skus()
    print(f"📊 Found {len(existing_skus)} SKUs in database")
    print()
    
    # Categorize SKUs
    generated_sku_codes = {sku['sku'] for sku in generated_skus}
    existing_sku_codes = set(existing_skus.keys())
    
    missing_sku_codes = generated_sku_codes - existing_sku_codes
    orphaned_sku_codes = {s for s in existing_sku_codes - generated_sku_codes
                          if not s.endswith('-MISC')}
    common_sku_codes = generated_sku_codes & existing_sku_codes
    
    # Find what needs to be inserted
    missing_skus = [sku for sku in generated_skus if sku['sku'] in missing_sku_codes]
    
    # Find what needs to be updated (description or other fields changed)
    skus_to_update = []
    for sku in generated_skus:
        if sku['sku'] in common_sku_codes:
            existing = existing_skus[sku['sku']]
            # Check if any field has changed
            if (existing['description'] != sku['description'] or
                existing['series'] != sku['series'] or
                existing['core_cable'] != sku['core_cable'] or
                existing['braid_material'] != sku['braid_material'] or
                existing['color_pattern'] != sku['color_pattern'] or
                existing['length'] != sku['length'] or
                existing['connector_type'] != sku['connector_type']):
                skus_to_update.append({
                    'sku': sku,
                    'old': existing
                })
    
    # Show results
    print("=" * 60)
    print(f"📊 Summary:")
    print(f"   Generated SKUs:     {len(generated_skus)}")
    print(f"   Existing in DB:     {len(existing_skus)}")
    print(f"   To insert:          {len(missing_skus)}")
    print(f"   To update:          {len(skus_to_update)}")
    print(f"   Orphaned in DB:     {len(orphaned_sku_codes)}")
    print("=" * 60)
    print()
    
    # Show orphaned SKUs (in database but not in YAML definitions)
    if orphaned_sku_codes:
        print("⚠️  Orphaned SKUs (in database but not in YAML definitions):")
        print()
        for sku_code in sorted(orphaned_sku_codes):
            sku_data = existing_skus[sku_code]
            print(f"   {sku_code:20} | {sku_data['series']:15} | {sku_data['color_pattern']}")
        print()
        print("   Note: These SKUs won't be deleted automatically.")
        print("   Remove them manually if they're no longer needed.")
        print()
    
    # Show missing SKUs
    if missing_skus:
        print(f"📋 Missing SKUs to insert:")
        print()
        for sku in missing_skus[:10]:  # Show first 10
            print(f"   {sku['sku']:20} | {sku['series']:15} | {sku['color_pattern']}")
        if len(missing_skus) > 10:
            print(f"   ... and {len(missing_skus) - 10} more")
        print()
    
    # Show SKUs to update
    if skus_to_update:
        print(f"📝 SKUs to update:")
        print()
        for item in skus_to_update[:10]:  # Show first 10
            sku = item['sku']
            old = item['old']
            print(f"   {sku['sku']:20}")
            if old['description'] != sku['description']:
                print(f"      Description: {old['description']}")
                print(f"                -> {sku['description']}")
        if len(skus_to_update) > 10:
            print(f"   ... and {len(skus_to_update) - 10} more")
        print()
    
    if not missing_skus and not skus_to_update:
        print("✅ All SKUs are up to date. Nothing to do!")
        return 0
    
    # Apply changes if requested
    if args.apply:
        print("💾 Applying changes to database...")
        print()
        
        inserted = 0
        updated = 0
        failed = 0
        
        # Insert missing SKUs
        if missing_skus:
            print("Inserting missing SKUs...")
            for sku in missing_skus:
                if insert_sku(sku):
                    print(f"   ✅ Inserted: {sku['sku']}")
                    inserted += 1
                else:
                    failed += 1
            print()
        
        # Update existing SKUs
        if skus_to_update:
            print("Updating existing SKUs...")
            for item in skus_to_update:
                if update_sku(item['sku']):
                    print(f"   ✅ Updated: {item['sku']['sku']}")
                    updated += 1
                else:
                    failed += 1
            print()
        
        print("=" * 60)
        print(f"✅ Sync complete!")
        print(f"   Inserted: {inserted}")
        print(f"   Updated:  {updated}")
        print(f"   Failed:   {failed}")
        print("=" * 60)
    else:
        print("ℹ️  This is a preview. Run with --apply to insert/update SKUs.")
        print(f"   Command: python util/sync_skus.py --apply")
    
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
