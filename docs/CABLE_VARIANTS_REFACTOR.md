# Cable Variants Refactor

**Status:** Phase 1 code complete (2026-04-29) — pending DB migration on DO host + smoke test. Phase 2 not started.

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

No placeholder rows in `cable_skus` for LTD — every edition gets a real, fully-populated `cable_skus` row. Slug is the SKU suffix; not stored separately.

### `greenlight/db.py` additions

```python
def create_ltd_edition(series_prefix, slug, event_name, length, description, operator, notes=None) -> dict
def list_ltd_editions(active_only=True, series_prefix=None) -> list[dict]
def get_ltd_edition(sku) -> dict | None
def update_ltd_edition_metadata(sku, event_name=None, notes=None) -> bool
def archive_ltd_edition(sku) -> bool
def unarchive_ltd_edition(sku) -> bool
```

`create_ltd_edition`:
- Validates slug `^[A-Z0-9]{4,12}$`
- Inserts into `cable_skus` (sku=`{prefix}-LTD-{slug}`, color_pattern='Limited Edition', length, description, etc.)
- Inserts into `cable_ltd_metadata` (sku, event_name, active=true, created_by=operator)
- Both inserts in one transaction; errors on slug collision

`list_ltd_editions`:
- Joins `cable_skus` + `cable_ltd_metadata` + a cable count subquery against `audio_cables`

### New screens in `greenlight/screens/cable.py`

- **`LtdEditionPickerScreen`** — lists active editions (slug, event name, series, length, cable count). Selection loads the cable_skus row → `ScanCableIntakeScreen` directly (no description prompt; that's set on the edition).
- **`LtdEditionCreateScreen`** — sequential prompts: series → slug (validated, dedup-checked) → event name → length → description (defaults to `f"Limited edition {event_name} — {length}ft"`) → calls `create_ltd_edition`, transitions to scan.

### Hook into scan flow

Two placement options for the LTD entry point. Decide during wiring:

- **Option A** — extra item on `SeriesSelectionScreen` (cable.py:1449): `[L] Limited Edition`, parallel to series choices. Picker shows editions across all series.
- **Option B** — extra item one level up (peer of "by SKU" / "by attributes"). Better matches operator mental model ("scanning Phish cables" not "scanning Studio Classic"), but requires touching the upstream menu.

### Settings — Manage Limited Editions

In `greenlight/screens/settings.py`:

- Add `"Manage Limited Editions"` to the menu (settings.py:14–20).
- New `LtdEditionsManagementScreen` — table view of all editions (active + archived) with cable counts. Filter toggle for active-only.
- New `LtdEditionDetailScreen` — view detail, edit `event_name` + `notes`, archive/unarchive. Show slug/length/description as read-only with note explaining they're locked.

### Shopify integration

- `ensure_dynamic_shopify_product` (renamed in Phase 1) handles both MISC and LTD — same code path; description and length come from `cable_skus`.
- `audio_shopify_inventory_reconcile.py` — `'-MISC-' in sku` branch widens to also match `'-LTD-'`.
- For LTD, optionally enrich Shopify product title with event name (e.g. "Studio Classic 10ft — Phish Summer Tour 2026").

### `shopify_app/`

After Phase 1 changes are deployed, LTD editions appear as ordinary `cable_skus` rows. Should "just work," but audit for any place that displays a SKU and might want to surface event name for LTDs.

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
