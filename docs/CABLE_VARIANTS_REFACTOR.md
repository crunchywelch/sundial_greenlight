# Cable Variants Refactor

**Status:** Phase 1 complete and shipped (2026-04-29). Phase 2 greenlight-side complete on main (bd2ee938, 2026-04-30); migration applied to prod DB (2026-05-05). **Phase 2 Shopify CRUD work paused** in favor of Phase 3 schema cleanup, decided 2026-05-05 after the LTD CRUD work surfaced longstanding sprawl in `cable_skus` (kind sentinels stuffed into `color_pattern`, `length` stored as text, `series`/`core_cable`/`braid_material`/`connector_type` denormalized per row when they're really per-prefix or per-SKU-derivable). Phase 2 LTD CRUD (the Shopify app routes + helpers) lands as-is for now and will be simplified once Phase 3 cleans up the underlying shape. No data is in `cable_ltd_metadata` yet so the cleanup window is open.

**Phase 3 readiness (2026-05-05 evening):** DO-side recon complete; Pi-side recon complete (added below); schema invariants, length backfill plan, pre-migration verification, and parity-test fixture format all incorporated. Ready for the user's final review before execution.

---

## Phase 3 — Schema cleanup (2026-05-05)

**Goal:** Stop denormalizing data that's already canonical in YAML config. Shrink `cable_skus` to its irreducible per-cable fields. Make derivations (kind, series, color name, defaults) a property of the SKU + config, not a column.

### What's actually in YAML today

The canonical sources of truth already exist:
- `util/product_lines/patterns.yaml` — color/pattern catalog: code → (name, fabric_type, description). E.g., `GL` → "Goldline", rayon, "Black rayon braid with gold tracer".
- `util/product_lines/{studio_classic,studio_vocal,tour_classic,tour_vocal}.yaml` — per-series files with `sku_prefix`, `core_cable`, `braid_material`, `lengths`, `connectors[]`, plus cost data.
- `util/product_lines/materials.yaml` — already used for weight calc.

`util/audio/audio_sync_skus.py` reads these YAMLs and writes the data row-by-row into `cable_skus`. Phase 3 inverts this: YAMLs stay canonical, and reads consult them (or a small DB-side mirror) instead of denormalized cable_skus columns.

### Design principle

YAML stays the single source of truth for cable config (series, patterns, materials). The DB stores per-cable irreducible state (sku, description, length-when-not-in-sku, audit). Both apps load the YAML at startup and resolve derivations in code. **No lookup tables. No backwards-compat view.** Anything that mirrors YAML into the DB is a drift hazard, and views built on hardcoded derivation just push the same drift into a different file. If a third consumer ever shows up, that's when we revisit a shared library or thin API — not before.

### Target shape for `cable_skus`

```
cable_skus (
  sku           TEXT PRIMARY KEY,
  description   TEXT,                   -- multi-role; see open question
  length        NUMERIC(5,2),           -- NULL for catalog (length is in the SKU); required for MISC/LTD
  archived_at   TIMESTAMPTZ,            -- soft-delete; replaces a separate active flag
  created_at    TIMESTAMPTZ,
  updated_at    TIMESTAMPTZ,
  CONSTRAINT length_required_for_variants CHECK (
    length IS NOT NULL
    OR NOT (sku ~ '-(MISC-[0-9]+|LTD-[A-Z0-9]{4,12})$')
  )
)
```

Dropped: `series`, `core_cable`, `braid_material`, `color_pattern`, `connector_type`. Length stays as a column (renamed type to `numeric(5,2)`) but is NULL for catalog SKUs (where the length token lives in the SKU string itself) and required for MISC/LTD (where the SKU doesn't encode it).

The CHECK constraint enforces "NULL for catalog, required for variants" structurally — without it, a future code path could insert a NULL-length MISC and silently break inventory math. Catalog rows are allowed NULL because the length token lives in the SKU string itself.

### `cable_ltd_metadata` cleanup

- Drop `active`. Active signal is `archived_at IS NULL`, matching the soft-delete pattern we're applying to `cable_skus`.
- Other columns stay as-is (event_name NOT NULL, archived_at, created_by, notes, created_at).

### Where derivations live

Two parallel implementations of the same SKU parser + YAML loader:

- **Python**: `greenlight/cable_config.py` (or extend the existing helpers) — loads `util/product_lines/*.yaml` once, exposes `series_for_prefix(prefix)`, `pattern_for_code(code)`, `parse_sku(sku) -> {prefix, length, color_code, connector_codes, kind}`.
- **JS**: `shopify_app/app/cable-config.server.js` — same surface, mirrored. Loads the same YAML files at server startup.
- **Parity test**: a fixture file `tests/sku_fixtures.json` listing `(sku, expected)` pairs is consumed by both a Python test and a JS test. Same input, same output, enforced by CI.

**Fixture format** (resolved in 3.2):

```json
[
  {"sku": "SC-12-RED-TS-TS", "expected": {
    "kind": "catalog", "series_prefix": "SC", "series": "Studio Classic",
    "length": 12, "pattern_code": "RED", "pattern_name": "Red Hot",
    "connectors": ["TS", "TS"]
  }},
  {"sku": "SC-MISC-42", "expected": {
    "kind": "misc", "series_prefix": "SC", "series": "Studio Classic"
  }},
  {"sku": "SC-LTD-PHISH26", "expected": {
    "kind": "ltd", "series_prefix": "SC", "series": "Studio Classic", "slug": "PHISH26"
  }}
]
```

Catalog cases carry length/pattern/connectors (parseable from the SKU); MISC/LTD cases don't (those values live in the DB row, not in the SKU). That asymmetry is explicit so neither parser is tempted to fake a value it can't derive.

**Real-SKU coverage**: synthetic fixtures alone won't catch a YAML edit that drops a color code. The fixture should include the full set of `cable_skus.sku` from prod (~46 MISC + the catalog set), with `expected` populated by running the resolver against the live YAML at fixture-generation time. Any future YAML change that breaks back-compat for an existing SKU surfaces immediately on test run.

Yes, two parsers is duplication. It's bounded (~50 lines each), the SKU shape is small, and the YAML format is fixed. The alternative (DB-side mirroring) drifts; the alternative (single-language helpers behind an API) is a much bigger commitment we don't need yet.

### Key derivation rules (from SKU shape)

- Catalog SKU `{prefix}-{length}{color}{?conn}`: prefix → series via YAML; length token → numeric; color token → pattern name via patterns.yaml; connector suffix → display string.
- MISC SKU `{prefix}-MISC-{n}`: prefix → series; length lives in `cable_skus.length`.
- LTD SKU `{prefix}-LTD-{slug}`: prefix → series; length lives in `cable_skus.length`.
- `kind(sku)` is determined by SKU shape: `*-MISC-{n}` → misc, `*-LTD-{slug}` → ltd, otherwise catalog.

### `audio_sync_skus.py` after Phase 3

Becomes ~30-50 lines: iterate over YAML-derived SKUs, ensure each `(sku, description)` row exists in `cable_skus`. No more series/core_cable/braid_material/color_pattern/connector_type fields to write. Stays as an idempotent CLI loader (run on demand or in CI), not folded into greenlight startup.

### Sequencing — big-bang consumer migration

Because there's no transitional view, all consumers update first, then a single migration drops the columns. With nothing in production for LTD and only two consumers (both in this repo), the coordination cost is low and the result is no transitional cruft.

1. **3.1 Recon** — DO-side complete (this commit). Pi-side recon needed before design freeze.
2. **3.2 Design review** — confirm description rename (or leave it), confirm parity-test format.
3. **3.3 Build the resolvers** — Python `cable_config.py` and JS `cable-config.server.js` + parity test. No DB changes yet. Both apps still happy on existing schema.
4. **3.4 Consumers migrate** — pi + DO in parallel. Every read site that pulls `series/color_pattern/connector_type/core_cable/braid_material` from `cable_skus` switches to reading the SKU + asking the in-process resolver. Length reads switch to either parsing the SKU (catalog) or reading `cable_skus.length` (MISC/LTD). Update `audio_sync_skus.py` to its minimal form. Ship as one PR per app or coordinated set.
5. **3.5 Migration** — once both apps are deployed on the new code, run the migration as a single transaction. Sub-steps:
   1. **Pre-migration parity check.** For every `cable_skus` row, compare the resolver's output against the existing column values (series/color_pattern/connector_type/length text). Any non-empty diff aborts the migration. Cheap insurance that the resolvers aren't returning stale or wrong derivations against real data — runs as a script before the SQL transaction begins.
   2. **Length backfill** (within the transaction):
      - `ALTER TABLE cable_skus ADD COLUMN length_num NUMERIC(5,2);`
      - Backfill variants only: `UPDATE cable_skus SET length_num = length::numeric WHERE sku ~ '-(MISC-[0-9]+|LTD-[A-Z0-9]{4,12})$' AND length ~ '^[0-9]+(\.[0-9]+)?$';`
      - Verify: `SELECT COUNT(*) FROM cable_skus WHERE sku ~ '-(MISC-|LTD-)' AND length_num IS NULL;` must be 0. If not, abort — anything that failed to parse needs a manual fix, not a silent NULL.
      - `ALTER TABLE cable_skus DROP COLUMN length; ALTER TABLE cable_skus RENAME COLUMN length_num TO length;`
   3. **Drop redundant columns**: `ALTER TABLE cable_skus DROP COLUMN series, DROP COLUMN core_cable, DROP COLUMN braid_material, DROP COLUMN color_pattern, DROP COLUMN connector_type;`
   4. **Apply CHECK constraint** for length (see Target shape above).
   5. **`cable_ltd_metadata.active`**: `ALTER TABLE cable_ltd_metadata DROP COLUMN active;` and update the partial index (`DROP INDEX idx_ltd_metadata_active; CREATE INDEX idx_ltd_metadata_active ON cable_ltd_metadata(archived_at) WHERE archived_at IS NULL;` — or drop the index entirely if `list_ltd_editions` ends up filtering some other way).
6. **3.6 Resume LTD CRUD** — `createLtdEdition` simplifies: drop the template-row SELECT entirely, just insert `(sku, description, length)` + sidecar. Series picker reads from YAML. Smoke test on the cleaned-up foundation.

### Phase 3.1 recon — DO-side consumer checklist

Reads of soon-to-be-derived columns. Each file switches from `SELECT cs.{series, color_pattern, ...} FROM cable_skus` to `SELECT cs.{sku, description, length} FROM cable_skus` plus an in-process call to the JS resolver (`cableConfig.attrsForSku(sku)` or similar). Length-from-SKU is parsed by the resolver for catalog rows; MISC/LTD read `cable_skus.length` directly.

| File | Reads |
|---|---|
| `shopify_app/app/routes/api.register-cable.jsx` | series, color_pattern, connector_type, core_cable, length |
| `shopify_app/app/routes/api.customer-cables.jsx` | series, color_pattern, connector_type, core_cable |
| `shopify_app/app/routes/api.order-fulfillment.jsx` | series, color_pattern, connector_type (3 query sites) |
| `shopify_app/app/routes/app._index.jsx` | series, length (as `sku_length`) |
| `shopify_app/app/routes/app.cables.$sku.jsx` | series, color_pattern |
| `shopify_app/app/routes/app.customer.$id.cables.jsx` | series, color_pattern, connector_type, core_cable |
| `shopify_app/app/routes/app.editions._index.jsx` | series, length, description |
| `shopify_app/app/routes/app.editions.$sku.jsx` | All (via `getEdition`) |
| `shopify_app/app/routes/app.editions.new.jsx` | connector_type (post-insert lookup) |
| `shopify_app/app/editions.server.js` | All (template-row read for create + getEdition) |
| `shopify_app/extensions/customer-cables-account/src/FullPage.jsx` | series, color, connector_type, length |
| `shopify_app/extensions/customer-cables-admin/src/BlockExtension.jsx` | length |

Writes (these go away or simplify):

| File | Writes |
|---|---|
| `util/audio/audio_sync_skus.py` | INSERTs/UPDATEs all derivable columns from YAML. Becomes: ensure cable_skus has a `(sku, description)` row for every YAML-generated SKU. Most of the script's write path collapses. |
| `shopify_app/app/editions.server.js` | INSERT into cable_skus with template-row copies. Simplifies to `(sku, description, length)` + sidecar — the template-row SELECT goes away entirely. |

Other files that touch the soon-to-be-derived columns and need updating:

- `util/audio/audio_shopify_sku_sync.py` — SELECT-then-format flow uses color_pattern/connector_type/length. Switches to reading `(sku, description, length)` from cable_skus + resolving the rest in Python.
- `util/audio/audio_shopify_price_sync.py` — `length` becomes numeric in the migration; existing `float(length_text)` parse becomes a direct read.
- `util/audio/audio_shopify_inventory_reconcile.py` — already uses sku-pattern checks; minimal impact.

### Phase 3.1 recon — Pi-side consumer checklist

Read sites in `greenlight/` that pull soon-to-be-derived columns from `cable_skus`. Each switches from `SELECT cs.{series, color_pattern, ...}` to `SELECT cs.{sku, description, length}` plus an in-process call to the Python resolver.

| File | Reads from cable_skus |
|---|---|
| `greenlight/db.py:get_audio_cable` (~85) | series, color_pattern, connector_type, core_cable, braid_material, length |
| `greenlight/db.py:get_cables_for_customer` (~607) | series, color_pattern, connector_type, length |
| `greenlight/db.py:get_all_cables` (~644) | series, color_pattern, connector_type, length |
| `greenlight/db.py:get_cables_for_order` (~879) | series, color_pattern, connector_type, length |
| `greenlight/db.py:get_available_inventory` (~700) | series, length, color_pattern, connector_type — also `WHERE cs.series = ?` filter |
| `greenlight/db.py:get_misc_summary` (~1104) | `GROUP BY cs.series` |
| `greenlight/db.py:get_available_series` (~1137) | `SELECT DISTINCT cs.series` |
| `greenlight/db.py:list_ltd_editions` / `get_ltd_edition` | series, length, description |
| `greenlight/db.py:get_or_create_misc_sku` (~346) | template-row SELECT for series/core_cable/braid_material/connector_type — **the entire template lookup goes away** in 3.4 |
| `greenlight/cable.py:CableType.load` | series, core_cable, braid_material, connector_type, length, color_pattern, description — class becomes resolver-backed wrapper around `(sku, description, length)` |
| `greenlight/screens/cable.py:build_cable_info_panel` (~167) | series, length, color_pattern, connector_type (consumes dict from `get_audio_cable`) |
| `greenlight/screens/orders.py` (~261, 475) | series, length, color_pattern (consumes dict from `get_cables_for_customer`) |
| `greenlight/hardware/tsc_label_printer.py` | series, length, color_pattern, connector_type (consumes label_data dict) |
| `greenlight/screens/inventory.py` | uses `get_available_inventory` — series filter |

Three sites need attention beyond a mechanical column-swap:

1. **`get_or_create_misc_sku` template lookup goes away.** The "find a representative row in this prefix to copy fields from" pattern dies. INSERT becomes `(sku, description, length)` only. Net code reduction.
2. **`WHERE cs.series = ?` filter in `get_available_inventory`.** Series is derived. Filter by SKU prefix instead (`WHERE cs.sku LIKE 'SC-%'`) — keeps the filtering pushed to the DB. The series-prefix mapping is in YAML so the screen looks up the prefix for the chosen series before querying.
3. **`GROUP BY cs.series` / `SELECT DISTINCT cs.series`.** Same problem. Either group/distinct by SKU prefix and resolve in Python, or read the series list directly from YAML and use it as the iteration source. The latter is cleaner — the YAML already has the canonical series list.

### Open design questions (carry into 3.2)

1. **`description` rename.** Today it plays three roles depending on SKU kind: vestigial (catalog), the discriminator/spec (MISC), marketing copy (LTD). Candidates considered: `display_note`, `variant_subtitle`, `subtitle`, `display_text`.

   *Recommendation*: leave it as `description`. The alternatives all feel less natural and the rename touches every consumer for marginal clarity gain. Document the role-per-kind convention in the schema comment and in this doc, and move on. Doesn't gate the migration — can revisit later if a clearer name surfaces in real use.

Resolved (2026-05-05):

- Length column stays on `cable_skus` as `numeric(5,2)` NULL — NULL for catalog, required for MISC/LTD, with CHECK constraint enforcing the rule structurally.
- No `cable_color_patterns` lookup table — apps load `patterns.yaml` directly.
- No `cable_series` lookup table — apps load per-series YAMLs directly.
- No `cable_skus_v` view — consumers update first, then migration drops columns (big-bang).
- SKU parser lives in app code, mirrored Python + JS, parity-tested. No SQL parsing functions.
- `audio_sync_skus.py` shrinks to its minimum form, stays a CLI loader (not folded into startup).
- Parity test fixture format: single `tests/sku_fixtures.json` listing `{sku, expected}` pairs (format above), consumed by both Python and JS tests. Real production SKUs included in the fixture so YAML edits that break back-compat surface immediately.
- Pre-migration parity check (3.5.1) before column drops — resolver output must match existing column values for every row in `cable_skus`, else abort.
- Length backfill (3.5.2) only for variant SKUs (MISC/LTD); aborts if any text length fails to parse cleanly.


## Implementation notes (2026-04-29)

Code-level deviations from the original plan worth recording:

- **Helper renames**: `ensure_special_baby_shopify_product` → `ensure_misc_shopify_product` (the plan said `ensure_dynamic_*` but that was forward-looking — the function still only handles MISC; Phase 2 can generalize). `update_special_baby_description` → `update_shopify_product_description` (the body was always SKU-generic). `get_special_baby_summary` → `get_misc_summary`.
- **Names that *stay* "special_baby"**: `_create_special_baby_product` and `get_cost_for_special_baby` refer to the customer-facing "Special Baby" Shopify product *brand name* (not the dying internal table), so those stay.
- **`effective_sku` field removed** from `assign_cable_to_order` and `get_cables_for_order` returns. After migration `audio_cables.sku` is the resolved SKU; the alias was a leftover. Callers in `orders.py` updated to use `cable['sku']` directly.
- **`special_baby_shopify_sku` field removed** from `get_audio_cable` return. Same reason.
- **MISC variants always use `color_pattern = 'Miscellaneous'`** in `cable_skus`. This is what the migration sets, and what `get_or_create_misc_sku` writes for new variants. The label printer still renders "Special Baby" branding for these (driven by `sku_kind(sku) == 'misc'`).
- **`sku_kind('SC-MISC')` returns `'catalog'`** — the placeholder rows are deleted by the migration, so this only matters if a hardcoded literal sneaks through. Treating it as catalog is harmless (no row exists to match).
- **`special_baby_types` was *also* used by `audio_shopify_price_sync.py`** — not flagged in the original plan. `build_special_baby_sku_map` rewritten to read MISC variants from `cable_skus`.

Two sequenced changes:

1. **Phase 1 — MISC unification.** Eliminate `special_baby_types`. Every MISC cable variant gets its own row directly in `cable_skus`. `audio_cables.sku` becomes the only FK needed.
2. **Phase 2 — LTD editions.** Branded limited-edition cable batches for festivals/bands. Built on the cleaned-up Phase 1 foundation.

Phase 1 ships and stabilizes before Phase 2 begins.

---

## Design rationale

### Why kill `special_baby_types`

- `cable_skus` contains 5 placeholder rows (`SC-MISC`, `TC-MISC`, etc.) that aren't real products — they exist purely to satisfy the `audio_cables.sku → cable_skus.sku` FK. The "catalog" table has a hidden asterisk.
- A MISC cable's identity is split between `audio_cables.sku` (placeholder) and `audio_cables.special_baby_type_id` (real variant). Two fields, neither sufficient alone.
- "What's the Shopify SKU for this cable?" requires `COALESCE(special_baby_types.shopify_sku, cable_skus.sku)`. Forget the LEFT JOIN and you silently get the wrong answer for ~5% of rows.
- `endswith('-MISC')` checks are scattered across `db.py`, `cable.py` (six places), `audio_shopify_sku_sync.py`, and `audio_shopify_inventory_reconcile.py`. The danger isn't the string check itself — it's that the check gates *whether to consult a second table*, which is the actual dual-source-of-truth hazard.

After the refactor: every cable has a real `cable_skus` row with full info. One FK, one source of truth, no conditional joins.

### Why no `kind` column

The SKU pattern already encodes the kind:

- `SC-12-RED-TS-TS` → catalog
- `SC-MISC-42` → misc
- `SC-LTD-PHISH26` → ltd

A `kind` column would denormalize information already present, with all the usual costs (drift, two sources of truth, redundant writes). Once the dual-table representation is gone, parsing the SKU is parsing the canonical identifier — not a hidden gating signal. A small `sku_kind(sku)` helper covers the read side.

### Why sidecar table for LTD metadata (not nullable columns on cable_skus)

LTD editions need fields that don't apply to other variants: `event_name`, `active`, `archived_at`, `created_by`, `notes`. Without a `kind` column, there's no structural way to enforce "required for LTD rows" via NOT NULL on `cable_skus`. A sidecar `cable_ltd_metadata` table:

- Enforces NOT NULL on required fields
- Existence of the sidecar row IS the authoritative "is this LTD?" answer
- Keeps `cable_skus` uniform — no nullable columns that apply to a minority of rows

The 1:1 is fine here because LTD is genuinely a specialization with extra metadata, not a workaround for an FK structure (which is what made `special_baby_types` hacky).

### Why no `slug` column on the sidecar

Slug is the suffix after `-LTD-` in the SKU itself. Storing it separately would be redundant.

---

## Resolved decisions

| Question | Decision |
|---|---|
| MISC dedup | Yes — same (series_prefix, description, length) shares one `cable_skus` row |
| Edit SKU after registration | No — locked from the app once any cable is registered against it; direct DB edits possible if absolutely needed |
| LTD slug format | `^[A-Z0-9]{4,12}$` |
| LTD sku format | `{series_prefix}-LTD-{slug}` (e.g. `SC-LTD-PHISH26`) |
| LTD metadata immutability | `event_name` and `notes` editable; slug, length, description locked once created |
| Phase ordering | Phase 1 merges and stabilizes before Phase 2 starts |
| LTD picker placement | TBD — Option A (item on `SeriesSelectionScreen`) vs Option B (peer of "by SKU" / "by attributes" one level up). Decide during Phase 2 wiring. |

---

## Phase 0 — Pre-work

- [x] Pull shopify_app changes from upstream (done 2026-04-29 — fast-forward of `api.order-fulfillment.jsx` and order-fulfillment extension; no schema/MISC-related files)
- [x] Reference scan — see findings below
- [ ] DB backup before running the Phase 1 migration

### Phase 0 reference scan findings

The scan turned up several files and call sites the original plan didn't enumerate. Most are mechanical, but two patterns are *silently dangerous* post-migration and must be fixed in Phase 1, not deferred.

**Silently dangerous patterns** — these check for SKUs ending in literal `-MISC` (the placeholder), which no row will have post-migration. They evaluate differently than before with no error:

| File:line | Current check | Post-migration behavior |
|---|---|---|
| `greenlight/db.py:1054` | `WHERE ac.sku NOT LIKE '%%-MISC'` (excludes MISC from per-SKU stock summary) | Filter becomes no-op → MISC variants flood the catalog stock report |
| `greenlight/db.py:1088` | `WHERE ac.sku NOT LIKE '%%-MISC'` (excludes MISC from recent sales) | Same — MISC sales appear in recent-sales report |
| `greenlight/db.py:1121` | `WHERE ac.sku LIKE '%%-MISC'` (selects MISC for special-baby summary) | Returns 0 rows — special-baby summary always empty |
| `greenlight/screens/cable.py:173,359,407,1132,2064` | `sku.endswith('-MISC')` (gates MISC display logic) | Always false → description field stops displaying for migrated MISC cables |
| `greenlight/screens/orders.py:260,474` | `cable['sku'].endswith('-MISC')` | Same |
| `greenlight/hardware/tsc_label_printer.py:305` | `sku.endswith('-MISC')` | Same — labels stop showing custom descriptions for MISC |
| `util/audio/audio_sync_skus.py:308` | `not s.endswith('-MISC')` filter | Filter becomes no-op |
| `util/audio/audio_shopify_sku_sync.py:134` | `not s.endswith('-MISC')` filter | Same |
| `shopify_app/extensions/customer-cables-admin/src/BlockExtension.jsx:23` | `!cable.sku.endsWith("MISC")` | Always true → tries to parse length from MISC SKU strings |
| `shopify_app/extensions/customer-cables-account/src/FullPage.jsx:119` | `!cable.sku.endsWith("MISC")` | Same |
| `shopify_app/app/routes/app._index.jsx:672` | `item.sku?.endsWith('MISC')` (chooses display length) | Always false → MISC cables display wrong length field |
| `shopify_app/app/routes/app.customer.$id.cables.jsx:73,147` | `cable.sku.endsWith("MISC")` | Same |

All of these must change to either:
- Pattern check for the new MISC SKU shape: `sku ~ '-MISC-[0-9]+$'` (SQL) or `sku.match(/-MISC-\d+$/)` (JS) / `sku_kind(sku) == 'misc'` (Python)
- Or simply removed — many of them are gating "show description" branches that no longer need gating since description lives uniformly on every `cable_skus` row.

**Additional files / call sites not in the original plan:**

- `greenlight/db.py:890` — another LEFT JOIN to `special_baby_types` beyond the ones already listed
- `greenlight/screens/cable.py:551` — second call site of `ensure_special_baby_shopify_product` (the first is at :361/:364)
- `greenlight/screens/orders.py:260, 474` — MISC display branches in the orders flow
- `greenlight/screens/__init__.py:21, 64` — exports `MiscCableEntryScreen`; update to new screen names
- `tests/test_label_printer.py:151` — uses literal `'sku': 'SC-MISC'`; will need a real-format MISC SKU

**`util/audio/audio_shopify_price_sync.py` — substantive new integration to migrate:**

This script has its own SELECT against `special_baby_types` (lines ~105–110) for cost/weight interpolation. It reads `(shopify_sku, base_sku, length)` and uses `length` to interpolate cost/weight from product line YAML, keyed off the series prefix derived from `base_sku`.

After migration this becomes:
```sql
SELECT sku, length::real
FROM cable_skus
WHERE sku ~ '-MISC-[0-9]+$' AND length IS NOT NULL
```
…and `base_sku` derivation changes from `base_sku.split('-')[0]` to `sku.split('-')[0]` (still the series prefix). Cost/weight interpolation logic stays as-is.

**`shopify_app/app/routes/api.order-fulfillment.jsx` — substantive rewrite (just merged from upstream):**

This file has three places doing the dual-FK lookup pattern (LEFT JOIN special_baby_types + `COALESCE(sbt.shopify_sku, ac.sku) AS sku`):
- Lines 58–69 (initial cables fetch)
- Lines 128–144 (refresh cables fetch)
- Lines 163–202 (single-cable lookup for assignment)

All three simplify dramatically: drop the LEFT JOIN, drop the `special_baby_shopify_sku` field aliasing, use `ac.sku` directly. Comment at line 199 ("Special babies use their shopify_sku from special_baby_types") becomes wrong and should be deleted.

### Updated Phase 1 file list

Adding the following to the file list in §Phase 1:

- `util/audio/audio_sync_skus.py` — drop the `endswith('-MISC')` filter
- `util/audio/audio_shopify_price_sync.py` — repoint `build_special_baby_sku_map` at `cable_skus`
- `greenlight/db.py:890` — additional LEFT JOIN cleanup
- `greenlight/db.py:1054, 1088, 1121` — three `LIKE '%-MISC'` queries need pattern updates
- `greenlight/screens/cable.py:551` — second `ensure_special_baby_shopify_product` call site
- `greenlight/screens/orders.py` — two MISC display branches
- `greenlight/screens/__init__.py` — export updates
- `greenlight/hardware/tsc_label_printer.py:305` — MISC display gate
- `tests/test_label_printer.py:151` — update test fixture SKU
- `shopify_app/app/routes/api.order-fulfillment.jsx` — three LEFT JOIN simplifications
- `shopify_app/app/routes/app._index.jsx:672` — display length logic
- `shopify_app/app/routes/app.customer.$id.cables.jsx:73, 147` — endsWith checks + description display
- `shopify_app/extensions/customer-cables-admin/src/BlockExtension.jsx:23` — endsWith check
- `shopify_app/extensions/customer-cables-account/src/FullPage.jsx:119` — endsWith check

---

## Phase 1 — Unify MISC into cable_skus

### Migration SQL

Single transaction. Run verification queries between steps and abort if counts don't match.

```sql
BEGIN;

-- 1. For each special_baby_types row, create a cable_skus row.
--    sbt.shopify_sku is already in the format we want (e.g. "SC-MISC-42") — use it as the new PK.
INSERT INTO cable_skus (sku, series, core_cable, braid_material, color_pattern,
                        length, connector_type, description)
SELECT sbt.shopify_sku,
       cs.series,
       cs.core_cable,
       cs.braid_material,
       'Miscellaneous',
       COALESCE(sbt.length::text, cs.length),
       cs.connector_type,
       sbt.description
FROM special_baby_types sbt
JOIN cable_skus cs ON sbt.base_sku = cs.sku
WHERE sbt.shopify_sku IS NOT NULL;

-- VERIFY: counts match
-- SELECT COUNT(*) FROM special_baby_types WHERE shopify_sku IS NOT NULL;
-- SELECT COUNT(*) FROM cable_skus WHERE sku ~ '-MISC-[0-9]+$';

-- 2. Repoint audio_cables.sku to the new variant SKUs.
UPDATE audio_cables ac
SET sku = sbt.shopify_sku
FROM special_baby_types sbt
WHERE ac.special_baby_type_id = sbt.id;

-- VERIFY: zero cables still on placeholder SKUs
-- SELECT COUNT(*) FROM audio_cables WHERE sku IN ('SC-MISC','SP-MISC','SV-MISC','TC-MISC','TV-MISC');

-- 3. Drop dead infrastructure.
ALTER TABLE audio_cables DROP COLUMN special_baby_type_id;
DROP TABLE special_baby_types;
DELETE FROM cable_skus WHERE sku IN ('SC-MISC','SP-MISC','SV-MISC','TC-MISC','TV-MISC');

-- 4. Sequence for new MISC variant SKUs going forward.
CREATE SEQUENCE cable_misc_variant_seq;
SELECT setval('cable_misc_variant_seq',
              GREATEST(1, (SELECT COALESCE(MAX(SUBSTRING(sku FROM '-MISC-([0-9]+)$')::int), 0)
                           FROM cable_skus WHERE sku ~ '-MISC-[0-9]+$')));

COMMIT;
```

### `util/audio/schema.sql`

- Remove `special_baby_types` CREATE TABLE block.
- Remove `special_baby_type_id` from `audio_cables`.
- Add `CREATE SEQUENCE cable_misc_variant_seq`.

### `greenlight/db.py`

**Delete:**
- `get_or_create_special_baby_type` (~db.py:332)
- `search_special_baby_types` (~db.py:393)
- The MISC-description-update helper (~db.py:290)

**Add:**
- `get_or_create_misc_sku(series_prefix, description, length) → str` — uses `pg_advisory_xact_lock(hashtext(series_prefix))` + lookup by (series, description, length, color_pattern='Miscellaneous'); on miss, `nextval('cable_misc_variant_seq')` and INSERT.
- `sku_kind(sku) → 'misc' | 'ltd' | 'catalog'` — small helper for branching code logic.

**Simplify:**
- `get_cable_record` — drop the `LEFT JOIN special_baby_types` and the description/length COALESCE.
- `register_scanned_cable` — drop the `special_baby_type_id` parameter and INSERT column.
- All other LEFT JOIN to `special_baby_types` (db.py:439, 587, 626, 694, 771) — delete join, delete `sbt.shopify_sku` / `sbt.description` references in SELECT, update consumers to read from `cable_skus` columns directly.

### `greenlight/screens/cable.py`

**Reflow MISC scan path.** Old:

```
ColorPatternSelectionScreen → "Misc" → MiscCableEntryScreen (length)
   → load SC-MISC base → ScanCableIntakeScreen
      → get_misc_cable_description prompts for description
      → get_or_create_special_baby_type
```

New:

```
ColorPatternSelectionScreen → "Misc" → MiscVariantPickerScreen
   → either pick existing variant (one cable_skus row each) or "[N] New" → MiscVariantCreateScreen (length + description)
   → resolve sku via get_or_create_misc_sku
   → ScanCableIntakeScreen (no description fork)
```

**File-level changes:**

- Replace `MiscCableEntryScreen` (cable.py:1573) with `MiscVariantPickerScreen` and `MiscVariantCreateScreen`.
- Delete `ScanCableIntakeScreen.get_misc_cable_description` (cable.py:1868) — its logic moves into `MiscVariantPickerScreen`.
- Update `ScanCableIntakeScreen.run` (cable.py:1835) — drop the `endswith('-MISC')` branch and all `special_baby_type_id` plumbing.
- Update `endswith('-MISC')` checks (cable.py:173, 359, 407, 1132, 2064) — most gate display logic that no longer needs special-casing now that description is on `cable_skus` for everyone. The few remaining become `sku_kind(sku) == 'misc'`.
- Tighten the registration-allow-update branch (cable.py:2063) — was specifically for re-linking a cable to a different `special_baby_type`. With one-row-per-variant + locked SKUs after registration, this branch can be deleted.

### `util/audio/` scripts

- **`audio_shopify_sku_sync.py`** — delete the second SELECT block (lines ~72–92) that unions `special_baby_types` into the SKU map. Delete the `endswith('-MISC')` filter (line ~134).
- **`audio_shopify_inventory_reconcile.py`** — remove the LEFT JOIN to `special_baby_types` (lines ~44, ~165). The `'-MISC-' in sku` branch at ~line 157 stays (still the right gate for "create the Shopify product on demand"), but no longer needs the JOIN — keys off the SKU pattern alone.

### `greenlight/shopify_client.py`

Rework `ensure_special_baby_shopify_product` to take a `cable_skus` row directly (sku, series, length, description) instead of a record-with-special-baby fields. Rename to `ensure_dynamic_shopify_product` so Phase 2 can reuse it for LTD.

### `shopify_app/`

After upstream pull, audit for the same patterns. Anything joining `special_baby_types` repoints at `cable_skus`. Anything reading the old `shopify_sku` column reads `cable_skus.sku` instead.

### Tests

`tests/test_misc_*.py` — three files reference MISC behavior. Update assertions about `special_baby_type_id` to use `cable_skus.sku`. Variant lookup behavior is preserved (dedup by description+length), so most assertions translate cleanly.

### Phase 1 verification queries

```sql
-- Every audio_cables row resolves to a valid SKU
SELECT COUNT(*) FROM audio_cables ac
LEFT JOIN cable_skus cs ON ac.sku = cs.sku
WHERE cs.sku IS NULL;  -- expect 0

-- Every MISC variant has description and length populated
SELECT COUNT(*) FROM cable_skus
WHERE sku ~ '-MISC-[0-9]+$' AND (description IS NULL OR length IS NULL);  -- expect 0

-- No cables still pointing at placeholder SKUs
SELECT COUNT(*) FROM audio_cables
WHERE sku IN ('SC-MISC','SP-MISC','SV-MISC','TC-MISC','TV-MISC');  -- expect 0
```

**Manual smoke tests:**
- Register a new MISC cable end-to-end, verify cable_skus row + scan screen displays correctly
- Register a duplicate MISC (same description + length) — should reuse the existing variant row
- Look up a previously migrated MISC cable by serial — verify all fields display

---

## Phase 2 — Add LTD editions

**Design split (decided 2026-04-30):** LTD edition CRUD lives in the Shopify app (Remix), not in the greenlight TUI. Greenlight is read-only on `cable_ltd_metadata` and provides the *picker* used during scan. Rationale: LTD editions are a catalog/product concept, the Shopify app is already the surface for product management, and operators creating an edition for "Phish Summer Tour 2026" are more naturally working in Shopify admin than at a QC station.

This also opens the door (Phase 2.5+) to deprecating `audio_sync_skus.py`'s YAML-driven catalog ingestion entirely and managing all SKUs in the Shopify app — but that's out of scope for Phase 2.

### Migration SQL

```sql
CREATE TABLE cable_ltd_metadata (
    sku TEXT PRIMARY KEY REFERENCES cable_skus(sku) ON DELETE CASCADE,
    event_name TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    archived_at TIMESTAMPTZ,
    created_by TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_ltd_metadata_active ON cable_ltd_metadata(active) WHERE active = TRUE;
```

No placeholder rows in `cable_skus` for LTD — every edition gets a real, fully-populated `cable_skus` row created by the Shopify app's CRUD UI. Slug is the SKU suffix (`{prefix}-LTD-{slug}`); not stored separately.

### Greenlight (read-only)

#### `greenlight/db.py`

- Update `sku_kind()` to recognize `{prefix}-LTD-{slug}` → `'ltd'`. Pattern: `parts[-2] == 'LTD' and parts[-1]` matches `^[A-Z0-9]{4,12}$`.
- Add `list_ltd_editions(active_only=True, series_prefix=None) -> list[dict]` — joins `cable_skus` + `cable_ltd_metadata` + a cable count subquery against `audio_cables`. Powers the picker.
- Add `get_ltd_edition(sku) -> dict | None` — single edition with metadata + cable count. Used for detail display.
- Enrich `get_audio_cable`, `get_cables_for_customer`, `get_all_cables`, `get_cables_for_order` to `LEFT JOIN cable_ltd_metadata` and surface `event_name` when present. The LEFT JOIN is appropriate here because the sidecar genuinely exists for some rows and not others — a true "extension" relationship, not a dual-source-of-truth hazard like the old `special_baby_types` join.

No write helpers in greenlight. The Shopify app owns those.

#### `greenlight/screens/cable.py`

- New `LtdEditionPickerScreen` — lists active editions (slug, event name, series, length, cable count) across all series. Selecting one loads the `cable_skus` row as `cable_type` and routes straight to `ScanCableIntakeScreen` (no description prompt — that's already on the edition).
- Empty-state when there are no active editions: surface a message directing the operator to create one in the Shopify app, and return.
- Hook: add `[L] Limited Edition` as an extra item on `SeriesSelectionScreen` (Option A from the previous draft — simplest). The picker bypasses the series funnel since the edition encodes the series.

#### Display (cable info panel + label printer)

- `build_cable_info_panel` — when `sku_kind(sku) == 'ltd'`, add a new "Event:" line showing the edition's `event_name` (sourced from the LEFT JOIN added above). Description still displays under the same gating used for MISC.
- `tsc_label_printer` — for LTD cables, render `event_name` instead of the "Special Baby" branding text used for MISC. Shape: probably "Limited Edition" or the event name itself on the line currently used for color/pattern. Confirm against the existing label layout for fit.

#### Inventory dashboard

Defer for now — `inventory.py` will list LTD variants alongside catalog (since they're just `cable_skus` rows with `kind='ltd'`). A dedicated "Limited Editions" summary panel can come as a small follow-up if you want it.

### Shopify app (separate work, on DO host)

The Shopify app is responsible for LTD edition lifecycle:

1. **CRUD UI** — list / create / edit metadata / archive editions. Lives wherever fits in the existing Remix app structure (e.g., `app/routes/app.editions.*`).
2. **Atomic write helper** — single transaction that inserts a `cable_skus` row (sku=`{prefix}-LTD-{slug}`, color_pattern='Limited Edition', length, description, series/core_cable/braid_material/connector_type from a representative row in the prefix) AND a `cable_ltd_metadata` row (event_name, created_by, active=true).
3. **Validation:**
   - Slug `^[A-Z0-9]{4,12}$`
   - Slug uniqueness (PK on `cable_skus.sku` enforces this for the full SKU)
   - Length > 0
   - Series prefix must exist in `cable_skus` (used as a template)
4. **Edit lock** — once an edition has registered cables (`SELECT COUNT(*) FROM audio_cables WHERE sku = ?` > 0), reject edits to slug/length/description. Allow `event_name`, `notes`, `active` toggle freely.
5. **Shopify product creation** — when an LTD edition is created in the CRUD UI, the Shopify app should also create the corresponding Shopify product (so it's available for sale). This is a Shopify-app-side concern; the existing `_create_special_baby_product` helper in greenlight is MISC-only and stays that way.

### Shopify integration (greenlight side)

- `ensure_misc_shopify_product` stays MISC-only. LTD products are created by the Shopify app's CRUD UI, not lazily by greenlight. So the existing `if sku_kind(sku) == 'misc'` branch in cable.py is correct as-is — LTD falls through to `set_inventory_for_sku` (the catalog path), which is what we want since the product is guaranteed to exist.
- `audio_shopify_inventory_reconcile.py` — the `'-MISC-' in sku` branch stays MISC-only for the same reason. LTD reconcile just sets quantity (no product creation needed).
- `audio_shopify_sku_sync.py` — already includes all `cable_skus` rows in the comparison; LTD SKUs appear automatically with no special handling.

### Tests

- `test_ltd_scan_flow.py` — insert a `cable_skus` + `cable_ltd_metadata` pair, register a cable, verify `get_audio_cable` surfaces `event_name`, verify `sku_kind('SC-LTD-PHISH26')` returns `'ltd'`.
- Test `list_ltd_editions(active_only=True)` excludes archived editions, and `series_prefix` filters correctly.

### Phase 2 verification queries

```sql
-- Every -LTD- SKU has a metadata sidecar
SELECT cs.sku FROM cable_skus cs
LEFT JOIN cable_ltd_metadata lm ON cs.sku = lm.sku
WHERE cs.sku ~ '-LTD-[A-Z0-9]+$' AND lm.sku IS NULL;  -- expect 0

-- And every metadata row has a SKU (FK enforces this, but worth confirming)
SELECT lm.sku FROM cable_ltd_metadata lm
LEFT JOIN cable_skus cs ON cs.sku = lm.sku
WHERE cs.sku IS NULL;  -- expect 0
```

**Manual smoke test (after both sides land):**
- Create an LTD edition via Shopify app, verify `cable_skus` + `cable_ltd_metadata` rows + Shopify product
- Open greenlight TUI, Register Cables → series → `[L] Limited Edition` → pick the edition → scan a cable
- Look up the registered cable by serial → verify "Event:" line in cable info panel
- Archive the edition in Shopify app → verify it disappears from greenlight's picker but lookup still works
- Verify order fulfillment (if any open orders contain LTD cables) shows event name correctly

### Tests

- `test_ltd_edition_create.py` — slug validation, dedup, sidecar atomicity
- `test_ltd_edition_lifecycle.py` — archive/unarchive, edit restrictions
- `test_ltd_scan_flow.py` — picking an edition routes to scan correctly

### Phase 2 verification queries

```sql
-- Every -LTD- SKU has a metadata sidecar
SELECT cs.sku FROM cable_skus cs
LEFT JOIN cable_ltd_metadata lm ON cs.sku = lm.sku
WHERE cs.sku ~ '-LTD-[A-Z0-9]+$' AND lm.sku IS NULL;  -- expect 0

-- And vice versa
SELECT lm.sku FROM cable_ltd_metadata lm
LEFT JOIN cable_skus cs ON cs.sku = lm.sku
WHERE cs.sku IS NULL;  -- expect 0
```

**Manual smoke tests:**
- Create LTD edition, scan a few cables, archive, verify it disappears from scan picker but stays in management view
- Look up an LTD-registered cable by serial, verify event name displayed
- Verify Shopify product appears with correct SKU and title

---

## Open items at start of work

- shopify_app/ pull may surface additional touchpoints not in this doc — note them as encountered
- LTD picker placement (Option A vs B) — decide during Phase 2 wiring after seeing the menu structure fresh
