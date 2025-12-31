#!/usr/bin/env python3
"""
Database migration: Add length column to audio_cables table

This allows MISC cables to have custom lengths stored directly on the cable record,
while regular cables continue to derive length from their SKU definition.
"""

from greenlight.db import pg_pool

def migrate():
    """Add length column to audio_cables table"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Check if column already exists
            cur.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'audio_cables' AND column_name = 'length'
            """)
            if cur.fetchone():
                print("✅ Column 'length' already exists in audio_cables table")
                return

            # Add length column (nullable, type REAL to match cable_skus.length)
            print("Adding 'length' column to audio_cables table...")
            cur.execute("""
                ALTER TABLE audio_cables
                ADD COLUMN length REAL
            """)
            conn.commit()
            print("✅ Successfully added 'length' column to audio_cables table")

    except Exception as e:
        print(f"❌ Error during migration: {e}")
        conn.rollback()
        raise
    finally:
        pg_pool.putconn(conn)

if __name__ == "__main__":
    print("Starting migration: Add length column to audio_cables")
    migrate()
    print("Migration complete!")
