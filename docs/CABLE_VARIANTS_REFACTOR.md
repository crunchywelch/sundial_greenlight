# Cable Variants Refactor

**Status:** Phase 6 shipped end-to-end (2026-05-07). Greenlight TUI and the
Shopify Remix app run against the current `sku_group`-based schema; YAML
config is split by audience (app-runtime vs back-office); LTD editions
span series natively. No outstanding migration work.

This document is the active spec for the cable identity model. Phases 1–5
were stepping stones to the current design; their detailed plans and
migrations live in git history (see [Earlier phases](#earlier-phases) below).

---

## Current model

Two tables describe a cable:

```
sku_group (
  sku          TEXT PK,           -- 'GL', 'SC-MISC-42', 'LTD-PHISH26'
  description  TEXT,              -- pattern name (catalog), free text (MISC), event name (LTD)
  archived_at  TIMESTAMPTZ        -- soft-delete (active = NULL)
)

audio_cables (
  serial_number   TEXT PK,
  sku_group       TEXT NOT NULL FK,
  prefix          TEXT NOT NULL,         -- 'SC' / 'SV' / 'TC' / 'TV' — series identity
  length          NUMERIC(5,2) NOT NULL,
  connector_code  TEXT NOT NULL,         -- '' (straight) or '-R' (right angle)
  -- + operator/test/customer/order fields
)
```

`sku_group.sku` is the **group identity** — the irreducible label for "what
kind of thing this is." The user-facing **variant SKU** string (what
Shopify and customers see — `SC-12GL`, `SC-12GL-R`, `SC-12-LTD-PHISH26-R`)
is computed from `(prefix, sku_group, length, connector_code)` at read
time, never stored.

The series prefix lives on `audio_cables`, not in the group SKU. This is
deliberate: an LTD edition can contain cables of any series, so encoding
series in the edition's group identity would be wrong.

| Kind | Group SKU | Variant SKU | Group spans series? |
|---|---|---|---|
| catalog | `GL`, `SL`, `BU` (pattern code) | `SC-12GL`, `TC-15BU-R` | Yes |
| MISC | `SC-MISC-42` (prefix-scoped) | equals group SKU | No (kept series-scoped) |
| LTD | `LTD-PHISH26` (slug only) | `SC-12-LTD-PHISH26-R` | Yes |

Series, construction (core_cable, braid_material), pattern names, and
connector display strings are derived from the SKU + the YAML config
under `util/product_lines/`. The DB tracks per-cable production state;
YAML is canonical for product-line spec.

## Resolver

Same surface in Python (`greenlight/cable_config.py`) and JS
(`shopify_app/app/cable-config.server.js`):

- `parse_group_sku(s)` — returns `kind` plus per-kind fields. Takes a
  `sku_group.sku`. Catalog: `pattern_code`, `pattern_name`. MISC:
  `prefix`, `series`, `misc_seq`. LTD: `slug`. (No prefix for catalog or
  LTD — those live on the cable.)
- `parse_variant_sku(s)` — takes a user-facing variant SKU string and
  returns `kind`, `group_sku` (derived back), and the per-cable attrs
  encoded in the string: `prefix`, `length`, `connector_code`,
  `connector_display`, plus the same identity fields as `parse_group_sku`.
- `format_variant_sku(prefix, group_sku, length, connector_code)` —
  inverse of `parse_variant_sku`. `prefix` is required for catalog and
  LTD; for MISC the group SKU already carries it and the helper just
  returns `group_sku`.
- `series_for_prefix`, `series_data_for_prefix`, `pattern_for_code`,
  `prefix_for_series`, `connector_display_for`, `all_prefixes`,
  `all_patterns` — YAML lookup helpers.

Round-trip identity: `format_variant_sku(parse_variant_sku(s)) == s` for
every variant. Enforced by `tests/sku_fixtures.json` (synthetic +
auto-generated prod) on both Python and JS sides.

## Resolved decisions

| Question | Decision |
|---|---|
| Where does series live? | `audio_cables.prefix` (per cable). Resolved from prefix via YAML for display. |
| Where does length live? | `audio_cables.length` (per cable). Catalog and LTD variant SKUs *also* encode length in the SKU string for derivation; the DB is the truth. |
| Where does connector_code live? | `audio_cables.connector_code` (per cable). Catalog and LTD variant SKUs encode the `-R` suffix; DB is the truth. |
| LTD slug format | `^[A-Z0-9]{4,24}$` |
| LTD group SKU format | `LTD-{slug}` (e.g. `LTD-PHISH26`) — series-agnostic |
| LTD variant SKU format | `{prefix}-{length}-LTD-{slug}{?-R}` — fully qualified per cable |
| MISC group SKU format | `{prefix}-MISC-{seq}` (sequence: `cable_misc_variant_seq`) — kept series-scoped |
| MISC variant SKU format | equal to group SKU |
| Catalog group SKU format | `{pattern_code}` (e.g. `GL`) — pattern only |
| Catalog variant SKU format | `{prefix}-{length}{pattern_code}{?-R}` (e.g. `SC-12GL-R`) |
| MISC dedup | By `(prefix, description)` — same description in same series shares one sku_group. Length is per-cable. |
| LTD CRUD ownership | Shopify Remix app. Greenlight reads only. |
| Catalog group seeding | Seeded once at migration time (the seven catalog groups). New patterns added later require a small follow-up migration; no auto-seeding helper exists. |
| Active/archived | `sku_group.archived_at IS NULL` means active. Soft-delete primarily for retired LTD editions. |
| Resolver location | Two parallel implementations (Python + JS), each ~150 lines, kept honest by `tests/sku_fixtures.json`. |
| YAML vs DB lookup tables | YAML is canonical. No DB-side mirror for series/patterns. |
| LTD on inventory dashboard | Hidden. LTD editions are merch-table inventory, not website inventory. Filtered at SQL + merge time. |

## YAML config

```
util/product_lines/
  patterns.yaml             # APP RUNTIME — pattern code → name + fabric_type
  cable_lines.yaml          # APP RUNTIME — per-series sku_prefix, lengths, connectors
  materials.yaml            # APP RUNTIME (narrow) — per-foot/connector weights for MISC product creation
  back_office/
    pricing.yaml            # back-office only — cost + price tables per series
    weights.yaml            # back-office only — per-length finished-product weights
```

Audience separation is the point. App runtime files are tiny and rarely
touched; back-office files are quarantined so editing pricing can't
break app startup. Every file has a header comment spelling out who
reads it and the blast radius of a bad edit.

## Code surface

### `greenlight/cable_config.py`
The Python resolver. Read-only on YAML; no DB dependency.

### `greenlight/db.py`
- `_enrich_record(record)` — central enrichment helper. Takes a dict with
  at least `sku_group`, `prefix` (and optionally `length`, `connector_code`,
  `description`); adds `kind`, `series`, `pattern_code`, `pattern_name`,
  `connector_display`, `core_cable`, `braid_material`, `variant_sku`. Every
  read path that returns cable records goes through this so consumers see
  one consistent dict shape.
- `register_scanned_cable(serial, sku_group, prefix, length, connector_code, ...)` —
  intake. Prefix, length, and connector_code are required.
- `get_or_create_misc_sku(prefix, description)` — dedup on description for
  MISC groups within a series; allocates a new `cable_misc_variant_seq`
  value if needed.
- `list_ltd_editions` / `get_ltd_edition` — read-only LTD lookups
  (greenlight is not the LTD CRUD owner). LTD editions span series, so
  these don't filter by prefix.
- `update_cable_description(serial, description)` — updates the cable's
  sku_group description. Only fires for MISC variants (catalog descriptions
  are pattern names from YAML; LTD descriptions are managed via Shopify).

### `greenlight/cable.py`
- `CableType` — sku_group wrapper. `.sku_group`, `.kind`, `.pattern_name`,
  `.description`. **Prefix, length, and connector_code are NOT on
  CableType** — they're per-cable, captured in the screen flow's nav
  context.
- `resolve_catalog_variant(series, color, length, connector)` — maps screen
  selections to `(sku_group, prefix, length, connector_code)`. The
  `sku_group` row is expected to exist (seeded at migration time).
- `get_distinct_*` discovery functions — YAML-backed (no DB queries).

### `greenlight/screens/cable.py`
Three scan flows; all converge on `register_scanned_cable(serial,
sku_group, prefix, length, connector_code, ...)`:

- **Catalog**: SeriesSelectionScreen → ColorPatternSelectionScreen →
  LengthSelectionScreen (YAML-listed lengths) → ConnectorTypeSelectionScreen →
  ScanCableIntakeScreen.
- **MISC**: ColorPatternSelectionScreen → MiscVariantPickerScreen
  (existing groups by description) → either pick or create
  (MiscVariantCreateScreen, description-only) → VariantLengthEntryScreen
  (free-form numeric) → ConnectorTypeSelectionScreen → scan.
- **LTD**: ColorPatternSelectionScreen → LtdEditionPickerScreen (active
  editions across all series) → VariantLengthEntryScreen →
  ConnectorTypeSelectionScreen → scan.

### Shopify app
LTD edition CRUD lives in `shopify_app/app/routes/app.editions.*` and the
`createLtdEdition` / `updateEdition` helpers in
`shopify_app/app/editions.server.js`. INSERT into `sku_group` is just
`(sku, description)` where `sku = LTD-{slug}`. Greenlight scans against
the existing rows.

`shopify_app/app/cable-config.server.js` is the JS resolver — same surface
as the Python side. Loads `patterns.yaml` + `cable_lines.yaml` at module
init; never touches `back_office/`.

The Shopify-app routes are split per-tab via a shared layout and tab bar
(`app/components/TabBar.jsx`, `app/routes/app.jsx`). Each tab is a
discrete URL: `/app/scan`, `/app/assign`, `/app/customers`,
`/app/inventory`, `/app/editions`. Tab navigation preserves the embedded
`host` param via `<Link>` + location.search.

### Util scripts
- `util/audio/audio_shopify_sku_sync.py` — variant-level SKU comparison
  between DB and Shopify. Walks distinct `(sku_group, prefix, length,
  connector_code)` tuples from `audio_cables`.
- `util/audio/audio_shopify_inventory_reconcile.py` — same shape, counts
  available cables per variant and compares to Shopify inventory.
- `util/audio/audio_shopify_price_sync.py` — sync prices/costs/weights
  to Shopify. Reads `back_office/pricing.yaml` and `back_office/weights.yaml`
  for catalog pricing; reads `audio_cables` for MISC variant lengths.
- `util/audio/generate_sku_fixtures.py` — regenerates
  `tests/sku_fixtures_prod.json` against current prod state. Run after
  any YAML edit that touches back-compat surface area.

### Tests
- `tests/test_sku_parity.py` and `shopify_app/tests/sku-parity.test.js`
  — fixture-driven. Load `tests/sku_fixtures.json` (synthetic) +
  `tests/sku_fixtures_prod.json` (auto-generated, optional). Both Python
  and JS parity tests share the same fixture file with `type` discriminator
  (`group` / `variant` / `round_trip`).
- `tests/test_catalog_scan_flow.py` — end-to-end catalog flow.
- `tests/test_misc_cable_length.py`, `tests/test_complete_misc_flow.py`,
  `tests/test_misc_display.py` — MISC flows.
- `tests/test_ltd_scan_flow.py` — LTD flow including archive lifecycle hooks.
- `tests/test_order_fulfillment.py` — `assign_cable_to_order` SKU
  validation against line items: match, mismatch, duplicate, cross-order.
- `tests/test_label_printer.py` — manual interactive label printing test.
- `shopify_app/scripts/smoke-test-ltd.mjs` — end-to-end LTD CRUD smoke
  test against prod. Cleans up after itself. Useful regression check
  whenever the LTD code path changes.

## Open follow-ups

Carry these forward but no urgent forcing function:

1. **Per-edition Shopify product mechanism** — there's currently no
   automatic Shopify product creation for LTD editions or new MISC
   variants. The `ensure_misc_shopify_product` helper still exists but
   isn't wired into any auto-create flow. Two design options ahead:
   (a) skip per-MISC/per-LTD Shopify products entirely (current
   behavior — sell as catalog cables with edition tag at fulfillment),
   (b) one product per edition with multiple length+connector variants
   created on demand. The user has flagged that LTD editions are
   merch-table inventory rather than website inventory, which mostly
   resolves the LTD side; revisit if/when website selling of LTD comes up.

## Sequence numbers / sequences in use

- `cable_misc_variant_seq` — generates the `{seq}` portion of MISC group
  SKUs (`{prefix}-MISC-{seq}`). Reset is unsupported; if MISC variants
  are ever pruned wholesale the sequence keeps advancing (intentional —
  never reuse a SKU).

## Earlier phases

Brief history of how we got here. Detailed plans + migrations live in
git history.

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
  into `sku_group.description`.
- **Phase 5** (shipped 2026-05-06) — dropped per-series prefix from catalog
  and LTD group identifiers. Catalog: `SC-GL` → `GL`. LTD: `SC-LTD-PHISH26`
  → `LTD-PHISH26` (the edition itself is series-agnostic; cables in it
  carry their own prefix). Added `audio_cables.prefix` column. MISC kept
  prefix-scoped to preserve `(prefix, description)` dedup.
- **Phase 5b** (2026-05-06) — extended LTD slug max length 12 → 24 chars
  to fit real-world edition names like `VINTAGEINTHEVALLEY2026`. LTD
  variant SKU shape changed to `{prefix}-{length}-LTD-{slug}{?-R}` so
  per-cable variation is fully qualified. LTD groups hidden from the
  inventory dashboard (merch-table inventory, not website inventory).
- **Phase 6** (shipped 2026-05-07) — split `util/product_lines/` YAML by
  audience. Per-series files consolidated into `cable_lines.yaml` (app
  runtime); cost/pricing/weight tables moved to `back_office/`. Each
  file has a header documenting its audience and blast radius.
