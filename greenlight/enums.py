import psycopg2
from greenlight.db import pg_pool

def fetch_enum_values(enum_type_name):
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT enumlabel
                FROM pg_enum
                JOIN pg_type ON pg_enum.enumtypid = pg_type.oid
                WHERE pg_type.typname = %s
                ORDER BY enumsortorder
            """, (enum_type_name,))
            return [row[0] for row in cur.fetchall()]
    except Exception as e:
        print(f"❌ Error fetching enums: {e}")
        conn.rollback()
    finally:
        pg_pool.putconn(conn)

