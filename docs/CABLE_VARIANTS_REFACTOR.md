# Cable Variants Refactor

**Status:** Phase 4 shipped end-to-end (2026-05-06). Greenlight TUI and Shopify
app both run against the `sku_group`-based schema. Phase 4 cleanup landed
(2026-05-06): backward-compat aliases dropped, dead code purged, tests added
for catalog and order-fulfillment paths. Util scripts re-verified clean
against the migrated DB.

This document is the active spec for the cable identity model. Phases 1–3
were stepping stones to the current design; their detailed plans live in
git history (see [Earlier phases](#earlier-phases) below).

---

## Current model

Two tables describe a cable:

```
sku_group (
  sku          TEXT PK,           -- 'SC-GL', 'SC-MISC-42', 'SC-LTD-PHISH26'
  description  TEXT,              -- pattern name (catalog), free text (MISC), event name (LTD)
  archived_at  TIMESTAMPTZ        -- soft-delete (active = NULL)
)

audio_cables (
  serial_number   TEXT PK,
  sku_group       TEXT NOT NULL FK,
  length          NUMERIC(5,2) NOT NULL,
  connector_code  TEXT NOT NULL,        -- '' (straight) or '-R' (right angle)
  -- + operator/test/customer/order fields
)
```

`sku_group.sku` is the **group identity**. The user-facing **variant SKU**
string (what Shopify and customers see — `SC-12GL`, `SC-12GL-R`) is computed
from `(sku_group, length, connector_code)` at read time, never stored.

For MISC and LTD groups, the variant SKU equals the group SKU (the SKU
string doesn't encode length/connector for those — those vary per cable).

Series, construction (core_cable, braid_material), pattern names, and
connector display strings are derived from the SKU + the YAML config under
`util/product_lines/`. YAML is canonical for catalog config; the DB only
tracks per-cable production state.

## Resolver

Same surface in Python (`greenlight/cable_config.py`) and JS
(`shopify_app/app/cable-config.server.js`):

- `parse_group_sku(s)` — kind/prefix/series + (pattern_code, pattern_name)
  for catalog, `misc_seq` for misc, `slug` for ltd. Takes a `sku_group.sku`.
- `parse_variant_sku(s)` — adds `group_sku`, `length`, `connector_code`,
  `connector_display` for catalog. MISC/LTD: `group_sku == sku`. Takes a
  user-facing variant SKU string.
- `format_variant_sku(group_sku, length, connector_code)` — inverse of
  `parse_variant_sku` for catalog. For MISC/LTD returns `group_sku`.
- `series_for_prefix`, `series_data_for_prefix`, `pattern_for_code`,
  `prefix_for_series`, `connector_display_for`, `all_prefixes`,
  `all_patterns` — YAML lookup helpers.

Round-trip identity: `format_variant_sku(parse_variant_sku(s)) == s` for
every catalog variant. Enforced by `tests/sku_fixtures.json` (synthetic +
prod) on both Python and JS sides.

## Resolved decisions

| Question | Decision |
|---|---|
| Where does series live? | Derived from SKU prefix via YAML. Not a column. |
| Where does length live? | `audio_cables.length` (per cable). Catalog SKUs *also* encode length in the SKU string for variant_sku formatting; the DB is the truth. |
| Where does connector_code live? | `audio_cables.connector_code` (per cable). Catalog SKUs encode `-R` suffix; DB is truth. |
| LTD slug format | `^[A-Z0-9]{4,12}$` |
| LTD sku format | `{prefix}-LTD-{slug}` (e.g. `SC-LTD-PHISH26`) |
| MISC sku format | `{prefix}-MISC-{seq}` (sequence: `cable_misc_variant_seq`) |
| Catalog group sku format | `{prefix}-{pattern_code}` (e.g. `SC-GL`) |
| MISC dedup | By `(prefix, description)` — same description in same series shares one sku_group. Length is per-cable. |
| LTD CRUD ownership | Shopify app (Remix). Greenlight reads only. |
| Catalog group seeding | Self-seeds via `ensure_catalog_sku_group(prefix, pattern_code)` on first cable registration with a new combo. The 14 catalog groups in prod were seeded by the Phase 4 migration. |
| Active/archived | `sku_group.archived_at IS NULL` means active. Soft-delete primarily for retired LTD editions. |
| Resolver location | Two parallel implementations (Python + JS), each ~150 lines, kept honest by `tests/sku_fixtures.json`. |
| YAML vs DB lookup tables | YAML is canonical. No DB-side mirror for series/patterns. |

## Code surface

### `greenlight/cable_config.py`
The Python resolver. Read-only on YAML; no DB dependency.

### `greenlight/db.py`
- `_enrich_record(record)` — central enrichment helper. Takes a dict with
  at least `sku_group` (and optionally `length`, `connector_code`,
  `description`); adds `kind`, `prefix`, `series`, `pattern_code`,
  `pattern_name`, `connector_display`, `core_cable`, `braid_material`,
  `variant_sku`. Every read path that returns cable records goes through
  this so consumers see one consistent dict shape.
- `register_scanned_cable(serial, sku_group, length, connector_code, ...)` —
  intake. Length and connector_code are required.
- `get_or_create_misc_sku(prefix, description)` — dedup on description for
  MISC groups; allocates a new `cable_misc_variant_seq` value if needed.
- `ensure_catalog_sku_group(prefix, pattern_code)` — INSERT-ON-CONFLICT for
  catalog groups; called by `resolve_catalog_variant`.
- `list_ltd_editions` / `get_ltd_edition` — read-only LTD lookups
  (greenlight is not the LTD CRUD owner).
- `update_cable_description(serial, description)` — updates the cable's
  sku_group description. Only fires for MISC variants (catalog descriptions
  are pattern names from YAML; LTD descriptions are managed via Shopify).

### `greenlight/cable.py`
- `CableType` — sku_group wrapper. `.sku_group`, `.kind`, `.prefix`,
  `.series`, `.pattern_name`, `.description`, `.core_cable`,
  `.braid_material`. **Length and connector_code are NOT on CableType** —
  they're per-cable, captured in the screen flow's nav context.
- `resolve_catalog_variant(series, color, length, connector)` — maps screen
  selections back through YAML to `(sku_group, length, connector_code)`.
  Auto-seeds the sku_group row.
- `get_distinct_*` discovery functions — YAML-backed (no DB queries).

### `greenlight/screens/cable.py`
Three scan flows; all converge on `register_scanned_cable(serial, sku_group,
length, connector_code, ...)`:

- **Catalog**: SeriesSelectionScreen → ColorPatternSelectionScreen →
  LengthSelectionScreen (YAML-listed lengths) → ConnectorTypeSelectionScreen →
  ScanCableIntakeScreen.
- **MISC**: ColorPatternSelectionScreen → MiscVariantPickerScreen
  (existing groups by description) → either pick or create
  (MiscVariantCreateScreen, description-only) → VariantLengthEntryScreen
  (free-form numeric) → ConnectorTypeSelectionScreen → scan.
- **LTD**: ColorPatternSelectionScreen → LtdEditionPickerScreen (active
  editions for the chosen series) → VariantLengthEntryScreen →
  ConnectorTypeSelectionScreen → scan.

### Shopify app
LTD edition CRUD lives in `shopify_app/app/routes/app.editions.*` and the
`createLtdEdition` / `updateEdition` helpers in
`shopify_app/app/editions.server.js`. INSERT into `sku_group` is just
`(sku, description)`. Greenlight scans against the existing rows.

`shopify_app/app/cable-config.server.js` is the JS resolver — same surface
as the Python side.

### Util scripts
- `util/audio/audio_shopify_sku_sync.py` — variant-level SKU comparison
  between DB and Shopify. Walks distinct `(sku_group, length,
  connector_code)` tuples from `audio_cables`.
- `util/audio/audio_shopify_inventory_reconcile.py` — same shape, counts
  available cables per variant and compares to Shopify inventory.
- `util/audio/audio_shopify_price_sync.py` — sync prices/costs/weights
  to Shopify. Reads YAML for catalog pricing; reads `audio_cables` for
  MISC variant lengths.
- `util/audio/generate_sku_fixtures.py` — regenerates
  `tests/sku_fixtures_prod.json` against current prod state. Run after
  any YAML edit that touches back-compat surface area.

### Tests
- `tests/test_sku_parity.py` — fixture-driven. Loads
  `tests/sku_fixtures.json` (synthetic) + `tests/sku_fixtures_prod.json`
  (auto-generated, optional). Both Python and JS parity tests share the
  same fixture file.
- `tests/test_catalog_scan_flow.py` — end-to-end catalog flow:
  resolve_catalog_variant + register + lookup + variant_sku round-trip.
- `tests/test_misc_cable_length.py`, `tests/test_complete_misc_flow.py`,
  `tests/test_misc_display.py` — MISC flows.
- `tests/test_ltd_scan_flow.py` — LTD flow including archive lifecycle
  hooks.
- `tests/test_order_fulfillment.py` — `assign_cable_to_order` SKU
  validation against line items: match, mismatch, duplicate, cross-order.
- `tests/test_label_printer.py` — manual interactive label printing test.

## Open follow-ups

Carry these forward but no urgent forcing function:

1. **`ensure_misc_shopify_product` semantics under per-cable length** —
   pre-Phase-4 each MISC variant (description+length tuple) had its own
   Shopify product; post-Phase-4 a MISC group can hold cables of multiple
   lengths but `ensure_misc_shopify_product` still creates one product per
   group with whichever length triggered the call. Two design options
   ahead: (a) skip per-MISC Shopify products entirely, or (b) one product
   with multiple length variants created on demand. Defer until either
   bites in operations or LTD per-edition product design forces a decision
   (same shape applies). Discuss with doclaude.

2. **Inventory dashboard rollups** — `get_available_inventory` groups by
   `(sku_group, length, connector_code)` per Phase 4. Some downstream UI
   may benefit from a higher-level rollup (per-group totals across
   lengths). Surface as needed.

## Sequence numbers / sequences in use

- `cable_misc_variant_seq` — generates the `{seq}` portion of MISC group
  SKUs (`{prefix}-MISC-{seq}`). Reset is unsupported; if MISC variants are
  ever pruned wholesale the sequence keeps advancing (intentional — never
  reuse a SKU).

## Earlier phases

Brief history of how we got here. Detailed plans + recon tables for each
phase are in git history.

- **Phase 1** (shipped 2026-04-29) — eliminated `special_baby_types`. Each
  MISC variant got its own `cable_skus` row. `audio_cables.sku` became the
  only FK needed.
- **Phase 2** (shipped 2026-04-30) — added LTD editions via a
  `cable_ltd_metadata` sidecar.
- **Phase 3** (2026-05-05) — schema cleanup pass. Resolver introduced;
  `cable_skus` shrunk to `(sku, description, length, archived_at, audit)`.
  Length normalized to `numeric(5,2)`. Series/color_pattern/connector_type
  columns dropped.
- **Phase 4** (2026-05-06) — surfaced the actual structural problem
  Phase 3 had been working around: `cable_skus` was conflating
  *sku-group identity* with *variant SKU identity*. Phase 4 split them:
  `sku_group` table holds groups, `audio_cables` carries length and
  connector, variant SKU strings are derived. Folded `cable_ltd_metadata`
  into `sku_group.description`. Final shape.
