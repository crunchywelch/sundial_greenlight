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

# Application constants
APP_NAME = "Greenlight Terminal"
APP_SUBTITLE = "Cable QC + Inventory Terminal"
EXIT_MESSAGE = "Thank you for using Greenlight!"

OPERATORS = {
    "ADW": "Aaron Welch",
    "ISS": "Ian Smith", 
    "EDR": "Ed Renauld",
    "SDT": "Sam Tresler",
}

# Hardware feature flags
USE_REAL_ARDUINO = os.getenv("GREENLIGHT_USE_REAL_ARDUINO", "false").lower() in ("true", "1", "yes")
USE_REAL_SCANNER = os.getenv("GREENLIGHT_USE_REAL_SCANNER", "true").lower() in ("true", "1", "yes")
USE_REAL_PRINTERS = os.getenv("GREENLIGHT_USE_REAL_PRINTERS", "false").lower() in ("true", "1", "yes")
USE_REAL_GPIO = os.getenv("GREENLIGHT_USE_REAL_GPIO", "true").lower() in ("true", "1", "yes")

# Arduino configuration
ARDUINO_PORT = os.getenv("GREENLIGHT_ARDUINO_PORT")  # e.g., "/dev/ttyUSB0"
ARDUINO_BAUDRATE = int(os.getenv("GREENLIGHT_ARDUINO_BAUDRATE", "9600"))

def get_op_name(code):
    return OPERATORS.get(code)

