import os
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "dbname": os.getenv("GREENLIGHT_DB_NAME"),
    "user": os.getenv("GREENLIGHT_DB_USER"),
    "password": os.getenv("GREENLIGHT_DB_PASS"),
    "host": os.getenv("GREENLIGHT_DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("GREENLIGHT_DB_PORT", 5432)),
}

def parse_operator_env():
    raw = os.getenv("GREENLIGHT_OPERATORS", "")
    return dict(
        entry.split("=", 1) for entry in raw.split(";") if "=" in entry
    )

def get_op_name(code):
    return OPERATORS.get(code)

OPERATORS = parse_operator_env()

