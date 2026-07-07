#!/usr/bin/env python3
"""
Build the cordset configurator catalog from raw Sundial Wire products.

Importable:  build_catalog(products, overrides=None) -> (catalog, diagnostics)
CLI:         reads wire_products_all.json [+ compat_overrides.json] in this
             directory and writes cordsets.catalog.json.

The catalog composes REAL component variants (wire-by-the-foot, plugs, switches,
sockets) that the form adds straight to the cart — so we only carry each
component's variant id, price, inventory, and enough attributes to drive
compatibility. Each wire gets a class id; each component carries the list of
wire classes it's compatible with (default rules, replaced per-variant by Ian's
verified overrides).
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from util.wire.cordset.classes import WIRE_CLASSES, classify, default_compat_classes

D = Path(__file__).parent


def _opts(p): return {o["name"]: o["values"] for o in (p.get("options") or [])}
def _colls(p): return [e["node"]["handle"] for e in p.get("collections", {}).get("edges", [])]
def _vars(p): return [e["node"] for e in p.get("variants", {}).get("edges", [])]
def _num_id(gid): return gid.rsplit("/", 1)[-1] if gid else None


def _gauge(title):
    m = re.search(r"(\d{2})\s*-?\s*GAUGE|\b(\d{2})G\b|\b(\d{2})/\d", title, re.I)
    return next((g for g in (m.groups() if m else []) if g), None)


def _conductors(p):
    t = p.get("title", "")
    for c in _colls(p):
        if c.startswith("2-conductor"):
            return 2
        if c.startswith("3-conductor"):
            return 3
    if re.search(r"3-?conductor|\b\d{2}/3\b|3C\b", t, re.I):
        return 3
    if re.search(r"2-?conductor|\b\d{2}/2\b|2C\b", t, re.I):
        return 2
    return None


def _style(p):
    hay = (p.get("title", "") + " " + " ".join(_colls(p))).lower()
    for s in ("overbraid", "pulley", "parallel", "twisted"):
        if s in hay:
            return s
    return None


def _heavy(p):
    t = p.get("title", "").upper()
    return "SJT" in t or "HEAVY-DUTY" in t or "HEAVY DUTY" in t


def _foot_variant(p):
    for v in _vars(p):
        so = " ".join(s["value"] for s in v["selectedOptions"]).lower()
        if "foot" in so:
            return v
    return None


_WIRE_STYLES = ("overbraid", "pulley", "parallel", "twisted")


def _is_wire(p):
    if p.get("status") != "ACTIVE":
        return False  # drop archived/draft — only sellable wire in the picker
    if "cord sets" in (p.get("tags") or []):
        return False
    if any(c in _colls(p) for c in ("plugs", "switches", "sockets")):
        return False
    t = p.get("title", "").upper()
    if "NOT USED" in t:
        return False
    if "ADDITIONAL FOOTAGE" in t:
        return False  # legacy fixed-length add-on; new model uses qty on the by-foot variant
    return _style(p) in _WIRE_STYLES and _foot_variant(p) is not None


def _compat_for(component, kind, overrides):
    """Override list wins if present for this variant; else default rules."""
    ov = (overrides or {}).get(kind, {})
    if component["variantId"] in ov:
        return list(ov[component["variantId"]])
    return default_compat_classes(component, kind)


def build_catalog(products, overrides=None):
    """Pure build: raw product nodes -> (catalog dict, diagnostics dict)."""
    wires, dropped = [], []
    for p in products:
        if not _is_wire(p):
            continue
        fv = _foot_variant(p)
        hay = (p["title"] + " " + " ".join(_colls(p))).lower()
        cond = _conductors(p)
        heavy = _heavy(p)
        cls = classify(_gauge(p["title"]), cond, _style(p), heavy)
        rec = {
            "productId": _num_id(p["id"]), "title": p["title"], "handle": p["handle"],
            "variantId": _num_id(fv["id"]), "sku": fv.get("sku"),
            "pricePerFoot": float(fv["price"]), "inventoryFeet": fv.get("inventoryQuantity"),
            "gauge": _gauge(p["title"]), "conductors": cond, "style": _style(p),
            "material": ("rayon" if "rayon" in hay else "cotton" if "cotton" in hay else None),
            "heavy": heavy, "classId": cls,
            "image": (p.get("featuredImage") or {}).get("url"),
        }
        if cls is None:
            dropped.append(rec["title"])
            continue
        wires.append(rec)

    def variants_of(p):
        out = []
        for v in _vars(p):
            vals = [s["value"] for s in v.get("selectedOptions", [])
                    if s["value"] and s["value"] != "Default Title"]
            out.append({"variantId": _num_id(v["id"]), "sku": v.get("sku"),
                        "price": float(v["price"]), "inventory": v.get("inventoryQuantity"),
                        "label": ", ".join(vals) if vals else "Standard",
                        "image": (v.get("image") or {}).get("url")})
        return out

    def axis_of(p):
        names = [o["name"] for o in (p.get("options") or []) if o["name"] != "Title"]
        return names[0] if names else None

    def base(p):
        vs = variants_of(p)
        return {
            "productId": _num_id(p["id"]), "title": p["title"],
            "variantAxis": axis_of(p), "variants": vs,
            # rep variant = the stable product key used for compat overrides & CSV
            "variantId": vs[0]["variantId"] if vs else None,
            "sku": "; ".join(dict.fromkeys(v["sku"] for v in vs if v["sku"])) or None,
            "price": min((v["price"] for v in vs), default=0.0),
            "inventory": sum((v["inventory"] or 0) for v in vs),
            "image": (p.get("featuredImage") or {}).get("url"),
        }

    plugs = []
    for p in products:
        if p.get("status") != "ACTIVE" or "plugs" not in _colls(p):
            continue
        t = p["title"].upper()
        if "COVER" in t or "FEMALE" in t or not _vars(p):
            continue
        rec = base(p)
        rec["prong"] = 3 if "3-prong-plugs" in _colls(p) else 2 if "2-prong-plugs" in _colls(p) else None
        rec["polarized"] = "(polarized)" in p["title"].lower()
        rec["compatClasses"] = _compat_for(rec, "plug", overrides)
        plugs.append(rec)

    STYLE_COLL = {
        "parallel": "switches-for-parallel-cord",
        "twisted": "switches-for-twisted-pair-wire",
        "pulley": "switches-for-pulley-and-overbraid-cord",
        "overbraid": "switches-for-pulley-and-overbraid-cord",
    }
    switches = []
    for p in products:
        if p.get("status") != "ACTIVE" or "switches" not in _colls(p) or not _vars(p):
            continue
        rec = base(p)
        rec["compatStyles"] = sorted({s for s, ch in STYLE_COLL.items() if ch in _colls(p)})
        rec["compatClasses"] = _compat_for(rec, "switch", overrides)
        switches.append(rec)

    sockets = []
    for p in products:
        if p.get("status") != "ACTIVE" or "sockets" not in _colls(p) or not _vars(p):
            continue
        if p["title"].upper().startswith("SOCKET RING"):
            continue  # shade support rings are accessories, not sockets
        rec = base(p)
        rec["grounded"] = "grounded-sockets" in _colls(p)
        rec["compatClasses"] = _compat_for(rec, "socket", overrides)
        sockets.append(rec)

    catalog = {
        "labor": {"note": "STUB — create a real Shopify assembly product & set price",
                  "variantId": None, "price": 5.00},
        "wireClasses": [c["id"] for c in WIRE_CLASSES],
        "compatSource": "verified-overrides" if overrides else "auto-derived",
        "wires": wires, "plugs": plugs, "switches": switches, "sockets": sockets,
    }
    diagnostics = {
        "wireCount": len(wires),
        "droppedUnclassified": dropped,
        "missingGauge": [w["title"] for w in wires if w["gauge"] is None],
        "missingConductors": [w["title"] for w in wires if w["conductors"] is None],
        "missingMaterial": [w["title"] for w in wires if w["material"] is None],
        "byClass": dict(Counter(w["classId"] for w in wires)),
        "plugs": len(plugs), "switches": len(switches), "sockets": len(sockets),
    }
    return catalog, diagnostics


def print_diagnostics(diag):
    print(f"wires={diag['wireCount']}  plugs={diag['plugs']}  "
          f"switches={diag['switches']}  sockets={diag['sockets']}")
    print("by class:", diag["byClass"])
    for k in ("droppedUnclassified", "missingConductors", "missingGauge", "missingMaterial"):
        n = len(diag[k])
        if n:
            print(f"  {k}: {n}  e.g. {diag[k][:3]}")


def main():
    products = json.loads((D / "wire_products_all.json").read_text())
    ov_path = D / "compat_overrides.json"
    overrides = json.loads(ov_path.read_text()) if ov_path.exists() else None
    catalog, diag = build_catalog(products, overrides)
    (D / "cordsets.catalog.json").write_text(json.dumps(catalog, indent=2))
    print_diagnostics(diag)
    print("compat source:", catalog["compatSource"])
    print("wrote cordsets.catalog.json")


if __name__ == "__main__":
    main()
