#!/usr/bin/env python3

"""
Cable SKU import utility for Greenlight application.
Imports cable SKU data from CSV file into the database.
"""

import sys
import os
import csv
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from greenlight.db import pg_pool

def import_cable_skus(csv_path='util/cable_skus.csv'):
    """Import cable SKUs from CSV file"""
    
    # Ensure CSV file exists
    csv_file = project_root / csv_path
    if not csv_file.exists():
        print(f"❌ CSV file not found: {csv_file}")
        return False
    
    print(f"📄 Reading CSV file: {csv_file}")
    
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            with open(csv_file, newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                count = 0
                errors = 0
                
                for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
                    try:
                        cur.execute('''
                            INSERT INTO cable_skus (
                                sku, series, core_cable, braid_material, 
                                color_pattern, length, connector_type, description
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (sku) DO UPDATE SET
                                series = EXCLUDED.series,
                                core_cable = EXCLUDED.core_cable,
                                braid_material = EXCLUDED.braid_material,
                                color_pattern = EXCLUDED.color_pattern,
                                length = EXCLUDED.length,
                                connector_type = EXCLUDED.connector_type,
                                description = EXCLUDED.description,
                                updated_at = CURRENT_TIMESTAMP
                        ''', (
                            row['SKU'],
                            row['Series'],
                            row['Core Cable'],
                            row['Braid Type'],
                            row['Color/Pattern'],
                            row['Length'],
                            row['Connectors'],
                            row['Description']
                        ))
                        count += 1
                        
                    except Exception as e:
                        print(f'⚠️  Error importing row {row_num} (SKU: {row.get("SKU", "unknown")}): {e}')
                        errors += 1
                        continue
                
                conn.commit()
                print(f'✅ Successfully imported {count} cable SKUs')
                if errors > 0:
                    print(f'⚠️  {errors} rows had errors and were skipped')
                
        # Show summary statistics
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM cable_skus')
            total = cur.fetchone()[0]
            print(f'📊 Total cable SKUs in database: {total}')
            
            cur.execute('''
                SELECT series, COUNT(*) 
                FROM cable_skus 
                GROUP BY series 
                ORDER BY series
            ''')
            print('\n📋 SKUs by series:')
            for series, series_count in cur.fetchall():
                print(f'   {series}: {series_count}')
                
            cur.execute('''
                SELECT connector_type, COUNT(*) 
                FROM cable_skus 
                GROUP BY connector_type 
                ORDER BY connector_type
            ''')
            print('\n🔌 SKUs by connector type:')
            for connector, connector_count in cur.fetchall():
                print(f'   {connector}: {connector_count}')
                
    except Exception as e:
        print(f'❌ Error importing cable SKUs: {e}')
        conn.rollback()
        return False
    finally:
        pg_pool.putconn(conn)
    
    return True

if __name__ == '__main__':
    success = import_cable_skus()
    sys.exit(0 if success else 1)
