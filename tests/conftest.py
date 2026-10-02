"""Keep pytest away from live services unless explicitly asked.

Scripts under tests/integration/ write real rows to Postgres and call
Shopify. They're only collected when GREENLIGHT_RUN_INTEGRATION=1.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if os.getenv("GREENLIGHT_RUN_INTEGRATION") != "1":
    collect_ignore = ["integration"]
