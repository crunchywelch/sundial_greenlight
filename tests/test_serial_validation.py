"""Serial validation must reject scanned retail UPCs (no DB needed)."""

import importlib
import sys
from unittest import mock

from greenlight.gtin import check_digit


def _db():
    # greenlight.db opens a connection pool at import; stub it so this test
    # stays offline.
    if "greenlight.db" not in sys.modules:
        with mock.patch("psycopg2.pool.SimpleConnectionPool"):
            importlib.import_module("greenlight.db")
    return sys.modules["greenlight.db"]


def _upc(first_eleven):
    return first_eleven + str(check_digit(first_eleven))


def test_serials_still_valid():
    v = _db().validate_serial_number
    for serial in ("1", "000123", "123456", "1234567"):
        assert v(serial) == (True, None), serial


def test_scanned_upc_rejected():
    ok, msg = _db().validate_serial_number(_upc("85000123456"))
    assert not ok
    assert "UPC" in msg


def test_12_digits_with_bad_check_digit_is_a_serial():
    upc = _upc("85000123456")
    bad = upc[:-1] + str((int(upc[-1]) + 1) % 10)
    assert _db().validate_serial_number(bad) == (True, None)
