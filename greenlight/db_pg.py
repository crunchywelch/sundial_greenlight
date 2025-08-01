import psycopg2
from psycopg2 import pool
from dotenv import load_dotenv
import os

load_dotenv()

DB_CONFIG = {
    "dbname": os.getenv("GREENLIGHT_DB_NAME"),
    "user": os.getenv("GREENLIGHT_DB_USER"),
    "password": os.getenv("GREENLIGHT_DB_PASS"),
    "host": os.getenv("GREENLIGHT_DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("GREENLIGHT_DB_PORT", 5432)),
}

# Create a connection pool (adjust min/max as needed)
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
    finally:
        pg_pool.putconn(conn)

