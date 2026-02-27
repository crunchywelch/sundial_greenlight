#!/usr/bin/env python3
"""
Simple menu for Sundial Wire data utilities.

Usage:
    python util/menu.py
"""

import subprocess
import sys
from pathlib import Path

UTIL_DIR = Path(__file__).parent
PYTHON = sys.executable

ACTIONS = [
    ("Refresh products from Shopify", [PYTHON, UTIL_DIR / "refresh_products.py"]),
    ("Pull inventory events from Shopify", [PYTHON, UTIL_DIR / "pull_inventory_events.py"]),
    ("Generate cost audit CSVs", [PYTHON, UTIL_DIR / "generate_cost_audit.py"]),
    ("Wire cost formula audit", [PYTHON, UTIL_DIR / "wire_cost_audit.py"]),
    ("Export inventory events CSV", [PYTHON, UTIL_DIR / "pull_inventory_events.py", "--export"]),
    ("Generate tax assessment (Schedule E)", [PYTHON, UTIL_DIR / "tax_assessment.py"]),
    ("Import source data (CSV/YAML → SQLite)", [PYTHON, UTIL_DIR / "import_sundial_data.py"]),
    ("Audit inventory policies (sell when OOS)", [PYTHON, UTIL_DIR / "audit_inventory_policy.py"]),
]


def main():
    while True:
        print()
        print("  Sundial Wire Data Utilities")
        print("  ===========================")
        for i, (label, _) in enumerate(ACTIONS, 1):
            print(f"  {i}. {label}")
        print(f"  q. Quit")
        print()

        choice = input("  > ").strip().lower()

        if choice == "q":
            break

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(ACTIONS):
                label, cmd = ACTIONS[idx]
                print()
                print(f"  Running: {label}")
                print(f"  {'─' * 50}", flush=True)
                subprocess.run([str(c) for c in cmd])
                print(f"  {'─' * 50}")
            else:
                print("  Invalid choice.")
        except ValueError:
            print("  Invalid choice.")


if __name__ == "__main__":
    main()
