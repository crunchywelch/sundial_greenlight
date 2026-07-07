#!/usr/bin/env python3
"""
Import Ian's verified hardware-compatibility CSV back into compat_overrides.json.

Reads the edited hardware_compat.csv (the file make_compat_csv.py produced, with
Ian's Y/N corrections) and emits compat_overrides.json:

    { "plug":   { "<variantId>": ["<wire class>", ...] },
      "switch": { ... },
      "socket": { ... } }

The next catalog build/sync folds these in, so the form and Sparky gate on
verified compatibility instead of the auto-derived guesses.

    venv/bin/python util/wire/cordset/import_compat_csv.py [path/to/edited.csv]
"""
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from util.wire.cordset.classes import CLASS_IDS

D = Path(__file__).parent
KIND_MAP = {"plug": "plug", "plugs": "plug", "switch": "switch", "switches": "switch",
            "socket": "socket", "sockets": "socket"}


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else (D / "hardware_compat.csv")
    rows = list(csv.reader(src.open()))

    # Skip any leading comment rows (start with '#'); the next row is the header.
    i = 0
    while i < len(rows) and rows[i] and rows[i][0].lstrip().startswith("#"):
        i += 1
    header = rows[i]
    data = rows[i + 1:]

    def col(name):
        return header.index(name)

    ci_type, ci_var = col("Type"), col("Shopify variantId")
    class_cols = {c: header.index(c) for c in CLASS_IDS if c in header}
    missing = [c for c in CLASS_IDS if c not in header]
    if missing:
        print(f"WARNING: header is missing class columns {missing} — is this the right CSV?")

    overrides = {"plug": {}, "switch": {}, "socket": {}}
    yes = unknown = 0
    for r in data:
        if not r or not r[ci_type].strip():
            continue
        kind = KIND_MAP.get(r[ci_type].strip().lower())
        vid = r[ci_var].strip()
        if not kind or not vid:
            continue
        compat = []
        for cls, ci in class_cols.items():
            cell = (r[ci].strip().upper() if ci < len(r) else "")
            if cell == "Y":
                compat.append(cls)
            elif cell not in ("N", ""):
                unknown += 1  # a leftover "?" or typo — treated as not-compatible
        overrides[kind][vid] = compat
        yes += len(compat)

    out = D / "compat_overrides.json"
    out.write_text(json.dumps(overrides, indent=2))
    counts = {k: len(v) for k, v in overrides.items()}
    print(f"wrote {out}")
    print(f"  components: {counts}   compatible pairings: {yes}")
    if unknown:
        print(f"  {unknown} non-Y/N cells (e.g. leftover '?') treated as NOT compatible — resolve in the sheet")


if __name__ == "__main__":
    main()
