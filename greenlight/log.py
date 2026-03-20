"""Centralized logging setup for Greenlight.

Call setup_logging() once at the top of every entry point (main.py, util
scripts, scanner_daemon).  All modules that already do
``logger = logging.getLogger(__name__)`` will automatically inherit the
root handler — no per-module changes needed.
"""

import logging
import logging.handlers
import os
import socket
from pathlib import Path

from greenlight.config import SYSLOG_PORT, LOG_LEVEL

_LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_FILE = _LOGS_DIR / "greenlight.log"
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_BACKUP_COUNT = 3

_configured = False


def setup_logging(name: str = "greenlight") -> None:
    """Configure the root logger with syslog + local file handlers.

    Safe to call multiple times — only the first call takes effect.
    """
    global _configured
    if _configured:
        return
    _configured = True

    hostname = socket.gethostname()
    ident = f"{name}@{hostname}"

    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    syslog_fmt = logging.Formatter(f"{ident}: %(name)s %(levelname)s %(message)s")
    file_fmt = logging.Formatter(f"%(asctime)s {ident}: %(name)s %(levelname)s %(message)s")

    root = logging.getLogger()
    root.setLevel(level)

    # --- Local rotating file (fallback) ---
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        _LOG_FILE, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT,
    )
    # Rotate on startup so each run gets a fresh log
    if _LOG_FILE.exists() and _LOG_FILE.stat().st_size > 0:
        file_handler.doRollover()
    file_handler.setFormatter(file_fmt)
    root.addHandler(file_handler)

    # --- Syslog over TCP ---
    try:
        syslog_handler = logging.handlers.SysLogHandler(
            address=("localhost", SYSLOG_PORT),
            socktype=socket.SOCK_STREAM,
        )
        syslog_handler.setFormatter(syslog_fmt)
        root.addHandler(syslog_handler)
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Could not connect to syslog on port %s: %s — logging to file only",
            SYSLOG_PORT, exc,
        )
