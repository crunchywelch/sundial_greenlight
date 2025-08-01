import psycopg2
from psycopg2 import pool
import os

from greenlight.config import DB_CONFIG

pg_pool = psycopg2.pool.SimpleConnectionPool(
    minconn=1,
    maxconn=5,
    **DB_CONFIG
)

def insert_test_result(serial, resistance, capacitance, operator=None, source_node=None):
    conn = pg_pool.getconn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO test_results 
                        (serial, resistance_ohms, capacitance_pf, operator, source_node)
                    VALUES (%s, %s, %s, %s, %s)
                """, (serial, resistance, capacitance, operator, source_node))
            conn.commit()
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        conn.rollback()
    finally:
        pg_pool.putconn(conn)

def init_db():
    conn = pg_pool.getconn()
    with conn.cursor() as cur:
        cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'cable_type') THEN
                        CREATE TYPE cable_type AS ENUM ('TS', 'TRS', 'XLR');
                    END IF;
                END$$;
            """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audio_cables (
                id SERIAL PRIMARY KEY,
                cable_type cable_type NOT NULL,
                serial TEXT UNIQUE NOT NULL,
                resistance_ohms REAL NOT NULL,
                capacitance_pf REAL NOT NULL,
                operator TEXT,
                source_node TEXT,
                label_version TEXT,
                notes TEXT,
                timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        """)

if __name__ == "__main__":
    init_pg_schema()
