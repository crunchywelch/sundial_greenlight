#!/usr/bin/env python3

# util/import_skus.py

"""
Legacy cable SKU import script.
DEPRECATED: Use ./util/04_import_skus.sh instead for standardized import process.
"""

import csv
import os
import warnings
import psycopg2
from dotenv import load_dotenv
from greenlight.db import pg_pool

# Show deprecation warning
warnings.warn(
    "This script is deprecated. Use ./util/04_import_skus.sh for standardized SKU import.",
    DeprecationWarning,
    stacklevel=2
)

CSV_PATH = "util/cable_skus.csv"

def init_db():
    try:
        conn = pg_pool.getconn()
        with conn.cursor() as cur:
            cur.execute("""
                DROP TABLE cable_skus
                """)
            cur.execute("""
                DROP TYPE series
                """)
            cur.execute("""
                DROP TYPE color_pattern
                """)
            cur.execute("""
                DROP TYPE connector_type 
                """)
            cur.execute("""
                DROP TYPE length 
                """)
            cur.execute("""
                DROP TYPE braid_material 
                """)
            cur.execute("""
                DROP TYPE core_cable_type 
                """)
            cur.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'series') THEN
                            CREATE TYPE series AS ENUM ('Studio Classic', 'Tour Classic', 'Studio Patch');
                        END IF;
                    END$$;
                """)
            cur.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'color_pattern') THEN
                            CREATE TYPE color_pattern AS ENUM ('Black', 'Oxblood', 'Cream', 'Vintage Tweed', 'Road Stripe');
                        END IF;
                    END$$;
                """)
            cur.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'connector_type') THEN
                            CREATE TYPE connector_type AS ENUM ('TS-TS', 'RA-TS', 'TRS-TRS', 'RTRS-TRS', 'XLR');
                        END IF;
                    END$$;
                """)
            cur.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'length') THEN
                            CREATE TYPE length AS ENUM ('0.5', '3', '6', '10', '15', '20');
                        END IF;
                    END$$;
                """)
            cur.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'braid_material') THEN
                            CREATE TYPE braid_material AS ENUM ('Cotton', 'Rayon');
                        END IF;
                    END$$;
                """)
            cur.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'core_cable_type') THEN
                            CREATE TYPE core_cable_type AS ENUM ('Canare GS-6');
                        END IF;
                    END$$;
                """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cable_skus (
                    sku TEXT PRIMARY KEY,
                    series series NOT NULL,
                    price NUMERIC(10, 2),
                    core_cable core_cable_type NOT NULL,
                    braid_material braid_material NOT NULL,
                    color_pattern color_pattern NOT NULL,
                    length length NOT NULL,
                    connector_type connector_type NOT NULL,
                    description TEXT
                )
            """)
        conn.commit()
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        conn.rollback()
    finally:
        pg_pool.putconn(conn)

def import_cable_types(csv_path=CSV_PATH):
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            with open(csv_path, newline='') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    cur.execute("""
                        INSERT INTO cable_skus (sku, series, price, core_cable, braid_material, color_pattern, length, connector_type, description)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (sku) DO NOTHING
                    """, (
                        row["SKU"],
                        row["Series"],
                        row["MSRP"],
                        row["Core Cable"],
                        row["Braid Type"],
                        row["Color/Pattern"],
                        row["Length"],
                        row["Connectors"].replace("-", "-"),
                        row["Description"]
                    ))
                    conn.commit()
        print("Cable types imported successfully.")
    except Exception as e:
        print(f"Error importing cable types: {e}")
        conn.rollback()
    finally:
        pg_pool.putconn(conn)

if __name__ == "__main__":
    init_db()
    import_cable_types()

