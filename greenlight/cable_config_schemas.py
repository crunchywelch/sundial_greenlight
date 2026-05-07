"""JSON Schema definitions for the YAML config files loaded at app startup.

Validated by cable_config.py at module init. Failures throw with a clear,
multi-error message rather than letting a malformed YAML produce silent
gaps in the resolver later (e.g. a typo'd sku_prefix that ends up in
nothing's series_for_prefix lookup).

Mirrors the JS schemas in shopify_app/app/cable-config-schemas.js — both
sides should stay in lockstep so DO-side and pi-side reject the same
malformed inputs.

Per-entry shape is locked down with additionalProperties=False so a typo
in a key gets caught immediately. The top-level container leaves
additionalProperties unset (default True) so back-office or comment-only
fields don't trip validation.
"""

PATTERNS_SCHEMA = {
    "type": "object",
    "required": ["patterns"],
    "properties": {
        "patterns": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["code", "name", "fabric_type"],
                "properties": {
                    "code": {"type": "string", "pattern": "^[A-Z]{2,3}$"},
                    "name": {"type": "string", "minLength": 1},
                    "fabric_type": {"type": "string", "enum": ["rayon", "cotton"]},
                    "description": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
}

CABLE_LINES_SCHEMA = {
    "type": "object",
    "required": ["series"],
    "properties": {
        "series": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "sku_prefix",
                    "product_line",
                    "core_cable",
                    "braid_material",
                    "lengths",
                    "connectors",
                ],
                "properties": {
                    "sku_prefix": {"type": "string", "pattern": "^[A-Z]{2,3}$"},
                    "product_line": {"type": "string", "minLength": 1},
                    "core_cable": {"type": "string", "minLength": 1},
                    "braid_material": {"type": "string", "enum": ["Rayon", "Cotton"]},
                    "lengths": {
                        "type": "array",
                        "items": {"type": "number", "exclusiveMinimum": 0},
                        "minItems": 1,
                    },
                    "connectors": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["code", "display"],
                            "properties": {
                                "code": {"type": "string"},  # '' or '-R' etc.
                                "display": {"type": "string", "minLength": 1},
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                "additionalProperties": False,
            },
        },
    },
}
