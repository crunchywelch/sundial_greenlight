#!/usr/bin/env python3
"""
Emit hardware_compat.csv for Ian to verify in Google Sheets.

Rows = each plug / switch / socket (real catalog components).
Columns = the nine wire classes (from classes.py).
Cells = prefilled Y / N / ? from the default rules; Ian edits, then
import_compat_csv.py folds his corrections back into the catalog.

    venv/bin/python util/wire/cordset/make_compat_csv.py
"""
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from util.wire.cordset.classes import (
    WIRE_CLASSES, CLASS_IDS, default_switch_compat, default_socket_compat,
)

D = Path(__file__).parent
cat = json.loads((D / "cordsets.catalog.json").read_text())


def yn(b): return "Y" if b else "N"


def plug_cell(p, cls):
    if cls["both"]:
        return "Y"
    if p.get("prong") is None:
        return "?"
    return yn(p["prong"] == cls["conductors"])


def variantcol(c):
    """Show the colour/finish axis and its values, e.g. 'Finish: brass, nickel'."""
    axis = c.get("variantAxis")
    vals = ", ".join(v["label"] for v in c.get("variants", []) if v["label"] != "Standard")
    return f"{axis}: {vals}" if axis and vals else ""


rows = []
for p in cat["plugs"]:
    attrs = f"{p.get('prong') or '?'}-prong" + (", polarized" if p.get("polarized") else "")
    rows.append(["PLUG", p["title"], p.get("sku") or "", f"{p['price']:.2f}", attrs, variantcol(p), p["variantId"]] +
                [plug_cell(p, c) for c in WIRE_CLASSES] + [""])
for s in cat["switches"]:
    attrs = "fits: " + ", ".join(s.get("compatStyles") or [])
    rows.append(["SWITCH", s["title"], s.get("sku") or "", f"{s['price']:.2f}", attrs, variantcol(s), s["variantId"]] +
                [yn(default_switch_compat(s, c)) for c in WIRE_CLASSES] + [""])
for s in cat["sockets"]:
    attrs = "grounded" if s.get("grounded") else ""
    rows.append(["SOCKET", s["title"], s.get("sku") or "", f"{s['price']:.2f}", attrs, variantcol(s), s["variantId"]] +
                [yn(default_socket_compat(s, c)) for c in WIRE_CLASSES] + [""])

header = ["Type", "Component", "SKU(s)", "Price", "Attributes (from catalog)", "Colors / finishes", "Shopify variantId"] + CLASS_IDS + ["Notes / corrections"]

out = D / "hardware_compat.csv"
with out.open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["# Y = compatible, N = not compatible, ? = please confirm. "
                "Edit any cell. Prefilled from auto-derived rules — please verify every one."])
    w.writerow(header)
    w.writerows(rows)

print(f"wrote {out} — {len(rows)} components x {len(CLASS_IDS)} wire classes")
