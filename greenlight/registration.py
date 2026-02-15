"""
Registration code generation for wholesale/reseller cables.

Generates unique XXXX-XXXX registration codes that end customers use to register
their cable on the Sundial website. Codes use a 30-character safe alphabet
(no 0/O/1/I/L/U to avoid confusion).
"""

import secrets

from greenlight.config import REGISTRATION_BASE_URL

# 30-char safe alphabet: A-Z minus O, I, L, U plus 0-9 minus 0, 1
# Removes visually ambiguous characters
SAFE_ALPHABET = "2345679ABCDEFGHJKMNPQRSTVWXYZ"  # 28 chars... let me count
# A B C D E F G H J K M N P Q R S T V W X Y Z = 22 letters (removed I, L, O, U)
# 2 3 4 5 6 7 8 9 = 8 digits (removed 0, 1)
# Total = 30 chars
SAFE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"

CODE_LENGTH = 8  # 4 + 4 with dash separator


def generate_registration_code():
    """Generate a cryptographically random registration code.

    Format: XXXX-XXXX using 30-char safe alphabet.
    Entropy: 30^8 = ~2.4 trillion combinations.

    Returns:
        str: Registration code in format "XXXX-XXXX"
    """
    chars = ''.join(secrets.choice(SAFE_ALPHABET) for _ in range(CODE_LENGTH))
    return f"{chars[:4]}-{chars[4:]}"


def generate_registration_url(code, base_url=None):
    """Build the full registration URL for a code.

    Args:
        code: Registration code (e.g., "XKDF-7M2P")
        base_url: Override base URL (defaults to config REGISTRATION_BASE_URL)

    Returns:
        str: Full URL like "https://sundial.audio/register?code=XKDF-7M2P"
    """
    url = base_url or REGISTRATION_BASE_URL
    return f"{url}?code={code}"
