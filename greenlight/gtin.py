"""GTIN-12 (UPC-A) validation and normalization.

Sundial's retail UPCs are GTIN-12s issued against our GS1 US company prefix.
The authoritative value for each cable variant lives in Shopify, on the
variant's `barcode` field — there is deliberately no UPC column in Postgres.
This module is the pure-function layer: check digits, validation, and
normalizing whatever a scanner or spreadsheet hands us into a canonical
12-digit string.

Nothing here touches the network or the database, so it is cheap to call from
label generation, import scripts, and scan loops alike.
"""

import logging
import re

logger = logging.getLogger(__name__)

_RE_DIGITS = re.compile(r'^\d+$')


def check_digit(first_eleven: str) -> int:
    """Compute the GTIN-12 check digit for the first 11 digits.

    Standard mod-10 weighting: odd positions (1-indexed from the left) are
    weighted 3, even positions 1, and the check digit is whatever brings the
    weighted sum up to a multiple of 10.

    Args:
        first_eleven: exactly 11 digits, as a string.

    Returns:
        The check digit as an int 0-9.

    Raises:
        ValueError: if the input isn't exactly 11 digits.
    """
    if not isinstance(first_eleven, str) or len(first_eleven) != 11 \
            or not _RE_DIGITS.match(first_eleven):
        raise ValueError(
            f"check_digit() needs exactly 11 digits, got {first_eleven!r}"
        )

    total = 0
    for i, ch in enumerate(first_eleven):
        weight = 3 if i % 2 == 0 else 1  # i=0 is position 1, an odd position
        total += int(ch) * weight

    return (10 - (total % 10)) % 10


def validate_gtin12(upc) -> tuple:
    """Check that a value is a well-formed GTIN-12 with a correct check digit.

    Mirrors the (ok, error_message) convention used by
    greenlight.db.validate_serial_number so callers can treat them alike.

    Args:
        upc: candidate value (anything; non-strings are rejected).

    Returns:
        (True, None) if valid, (False, error_message) otherwise.
    """
    if not isinstance(upc, str) or not upc.strip():
        return False, "UPC is empty"

    s = upc.strip()

    if not _RE_DIGITS.match(s):
        return False, f"Invalid UPC '{s}' — must be digits only"

    if len(s) != 12:
        return False, f"Invalid UPC '{s}' — must be 12 digits, got {len(s)}"

    expected = check_digit(s[:11])
    if int(s[11]) != expected:
        return False, (
            f"Invalid UPC '{s}' — check digit is {s[11]}, expected {expected}"
        )

    return True, None


def is_valid_gtin12(upc) -> bool:
    """True if `upc` is a well-formed GTIN-12. See validate_gtin12()."""
    ok, _ = validate_gtin12(upc)
    return ok


def normalize_gtin12(raw):
    """Coerce assorted real-world UPC spellings into a canonical GTIN-12.

    Handles the forms we actually see:
      - 12 digits — validated and returned as-is.
      - 14 digits with two leading zeros — GS1 Data Hub exports every GTIN
        in the 14-digit GTIN-14 field, so a UPC-A arrives as 00 + 12 digits.
        The zeros are stripped.
      - 13 digits with a leading zero — an EAN-13-configured scanner reporting
        a UPC-A. The leading zero is stripped.
      - 11 digits — a spreadsheet that dropped the check digit (or Excel
        helpfully treating it as a number). The check digit is computed.

    Separators humans add (spaces, hyphens) are removed first.

    Args:
        raw: the value to normalize.

    Returns:
        A canonical 12-digit string, or None if it can't be made into a valid
        GTIN-12. Callers that want to tell the user *why* should use
        validate_gtin12() on the result of their own cleanup instead.
    """
    if not isinstance(raw, str):
        return None

    s = re.sub(r'[\s\-]', '', raw.strip())
    if not s or not _RE_DIGITS.match(s):
        return None

    if len(s) == 14 and s.startswith('00'):
        s = s[2:]
    elif len(s) == 13 and s[0] == '0':
        s = s[1:]
    elif len(s) == 11:
        s = s + str(check_digit(s))

    return s if is_valid_gtin12(s) else None


def upca_payload(upc12: str) -> str:
    """Return the 11 digits TSPL's UPCA barcode type expects.

    The TE210 computes and appends the check digit itself, so we hand it the
    first 11 digits only. We still store and validate all 12, which makes the
    printer's arithmetic an independent cross-check on ours: if the digit it
    renders disagrees with the one in Shopify, the label is visibly wrong.

    Args:
        upc12: a valid GTIN-12 (see validate_gtin12).

    Returns:
        The first 11 digits.

    Raises:
        ValueError: if `upc12` isn't a valid GTIN-12.
    """
    ok, err = validate_gtin12(upc12)
    if not ok:
        raise ValueError(err)
    return upc12[:11]


def looks_like_gtin12(raw) -> bool:
    """True if `raw` is probably a scanned UPC rather than a cable serial.

    Serial numbers are purely numeric too (see db.validate_serial_number), so
    a scan loop that accepts serials will happily swallow a 12-digit UPC and
    zero-pad it into a bogus serial. Scan handlers should call this first and
    reject the input as a product barcode before treating it as a serial.

    Deliberately length-based and check-digit-aware rather than just
    `len == 12`: a hypothetical 12-digit serial would fail the check digit and
    still be handled as a serial.
    """
    if not isinstance(raw, str):
        return False
    s = re.sub(r'[\s\-]', '', raw.strip())
    if len(s) not in (12, 13, 14):
        return False
    return normalize_gtin12(s) is not None
