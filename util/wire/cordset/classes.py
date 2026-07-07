"""
Wire classes + default hardware-compatibility rules for the cordset configurator.

Single source of truth shared by the catalog builder (derive/sync), the
compatibility-CSV generator, and the CSV importer. Compatibility is a property
of the wire *class* (gauge / conductors / style), not the individual colour, so
everything keys off these nine classes — the same ones the legacy cordset
products were organised by.
"""

WIRE_CLASSES = [
    {"id": "14g Pulley",        "gauge": 14,   "conductors": 3, "style": "pulley",    "both": False},
    {"id": "16g Twisted",       "gauge": 16,   "conductors": 2, "style": "twisted",   "both": False},
    {"id": "18g Twisted",       "gauge": 18,   "conductors": 2, "style": "twisted",   "both": False},
    {"id": "20g Twisted",       "gauge": 20,   "conductors": 2, "style": "twisted",   "both": False},
    {"id": "22g Twisted",       "gauge": 22,   "conductors": 2, "style": "twisted",   "both": False},
    {"id": "2-cond 18g Pulley", "gauge": 18,   "conductors": 2, "style": "pulley",    "both": False},
    {"id": "3-cond 18g Pulley", "gauge": 18,   "conductors": 3, "style": "pulley",    "both": False},
    {"id": "16g 3-cond Pulley", "gauge": 16,   "conductors": 3, "style": "pulley",    "both": False},
    {"id": "18g SJT Heavy Duty","gauge": 18,   "conductors": 3, "style": "pulley",    "both": False},
    {"id": "Overbraid 3-cond",  "gauge": None, "conductors": 3, "style": "overbraid", "both": True},
    {"id": "Parallel",          "gauge": 18,   "conductors": 2, "style": "parallel",  "both": False},
]
CLASS_BY_ID = {c["id"]: c for c in WIRE_CLASSES}
CLASS_IDS = [c["id"] for c in WIRE_CLASSES]

_TWISTED = {"16": "16g Twisted", "18": "18g Twisted", "20": "20g Twisted", "22": "22g Twisted"}


def classify(gauge, conductors, style, heavy=False):
    """Map a wire's (gauge, conductors, style, heavy) to a class id, or None.

    Gauge/heavy-duty only distinguish compatibility where it actually matters
    (14g pulley, the twisted gauges, and the SJT heavy-duty pulleys); otherwise
    a representative class is used so every real wire lands somewhere.
    """
    if not style:
        return None
    g = str(gauge) if gauge is not None else None
    if style == "overbraid":
        return "Overbraid 3-cond"
    if style == "parallel":
        return "Parallel"
    if style == "twisted":
        return _TWISTED.get(g, "18g Twisted")
    if style == "pulley":
        if g == "14":
            return "14g Pulley"          # its own class so compat can differ from 18g
        if heavy:
            return "16g 3-cond Pulley" if g == "16" else "18g SJT Heavy Duty"
        if g == "16" and conductors == 3:
            return "16g 3-cond Pulley"
        if conductors == 3:
            return "3-cond 18g Pulley"
        return "2-cond 18g Pulley"
    return None


# --- default compatibility rules (overridden by Ian's verified CSV) ----------

def default_plug_compat(plug, cls):
    if cls["both"]:            # grounded overbraid accepts 2- or 3-prong
        return True
    prong = plug.get("prong")
    if prong is None:
        return True            # unknown prong — permissive, flagged as "?" in the CSV
    return prong == cls["conductors"]


def default_switch_compat(switch, cls):
    return cls["style"] in (switch.get("compatStyles") or [])


def default_socket_compat(socket, cls):
    if socket.get("grounded"):
        return cls["conductors"] == 3
    return True


DEFAULT_COMPAT = {
    "plug": default_plug_compat,
    "switch": default_switch_compat,
    "socket": default_socket_compat,
}


def default_compat_classes(component, kind):
    """List of class ids a component is compatible with, per the default rules."""
    fn = DEFAULT_COMPAT[kind]
    return [c["id"] for c in WIRE_CLASSES if fn(component, c)]
