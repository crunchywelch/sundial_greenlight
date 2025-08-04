# util/create_audio_cables_table.py

"""
Database setup script to create the audio_cables table for storing production records.
Run this once to set up the production database.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from greenlight.db import pg_pool

def create_audio_cables_table():
    """Create the audio_cables table and associated sequence"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            print("Creating audio_cable_serial_seq sequence...")
            cur.execute("""
                CREATE SEQUENCE IF NOT EXISTS audio_cable_serial_seq START 1;
            """)
            
            print("Creating audio_cables table...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS audio_cables (
                    serial_number TEXT PRIMARY KEY,
                    sku TEXT NOT NULL,
                    resistance_ohms REAL,
                    capacitance_pf REAL,
                    operator TEXT,
                    arduino_unit_id INTEGER,
                    notes TEXT,
                    test_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    
                    FOREIGN KEY (sku) REFERENCES cable_skus(sku)
                );
            """)
            
            print("Creating indexes for better performance...")
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_audio_cables_sku ON audio_cables(sku);
                CREATE INDEX IF NOT EXISTS idx_audio_cables_operator ON audio_cables(operator);
                CREATE INDEX IF NOT EXISTS idx_audio_cables_timestamp ON audio_cables(test_timestamp);
                CREATE INDEX IF NOT EXISTS idx_audio_cables_arduino_unit ON audio_cables(arduino_unit_id);
            """)
            
            conn.commit()
            print("✅ Audio cables table created successfully!")
            
    except Exception as e:
        print(f"❌ Error creating audio_cables table: {e}")
        conn.rollback()
        return False
    finally:
        pg_pool.putconn(conn)
    
    return True

def check_table_exists():
    """Check if the audio_cables table already exists"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'audio_cables'
                );
            """)
            return cur.fetchone()[0]
    except Exception as e:
        print(f"❌ Error checking table existence: {e}")
        return False
    finally:
        pg_pool.putconn(conn)

def main():
    print("🔧 Setting up audio_cables production database...")
    
    if check_table_exists():
        print("⚠️  Audio cables table already exists!")
        choice = input("Do you want to recreate it? This will delete all existing data! (y/N): ")
        if choice.lower() != 'y':
            print("Aborted.")
            return
        
        # Drop existing table
        conn = pg_pool.getconn()
        try:
            with conn.cursor() as cur:
                print("Dropping existing table...")
                cur.execute("DROP TABLE IF EXISTS audio_cables CASCADE;")
                cur.execute("DROP SEQUENCE IF EXISTS audio_cable_serial_seq CASCADE;")
                conn.commit()
        except Exception as e:
            print(f"❌ Error dropping table: {e}")
            return
        finally:
            pg_pool.putconn(conn)
    
    if create_audio_cables_table():
        print("\n🎉 Database setup complete!")
        print("The audio_cables table is ready to store production records.")
    else:
        print("\n❌ Database setup failed!")

if __name__ == "__main__":
    main()
