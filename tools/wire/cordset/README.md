# Cord Set Configurator

Customer-facing cord set / pendant builder for the **Sundial Wire** storefront.
Customers pick a wire, terminate each end (plug / socket / switch), and the exact
Shopify component variants are added to their cart.

## Architecture (the important part)

- **No backend.** The configurator is a **theme app extension** (an app block) in a
  separate Shopify app. It loads the catalog this tooling publishes and calls the storefront
  `/cart/add.js` directly — no server, no App Proxy, no draft orders.
- **Components-in-cart.** Each cord set adds its real component variants as separate
  cart lines — wire (`qty` = feet) + plug + optional socket + optional switch +
  optional labor product — bound by a `_cordset` line-item property. So Shopify
  decrements real inventory and prices are always the live Shopify prices.
- **The app repo is separate:** `~/projects/sundial-cordsets/` (its own git repo,
  extension-only app, installed on the `sundial-wire` store). The extension lives at
  `extensions/cordset-configurator/`, and **all the builder's code lives there** —
  edit it in that repo. The tooling here (in greenlight) only builds and publishes
  the catalog it reads.

## Files here (`tools/wire/cordset/`)

| File | Role |
|---|---|
| `classes.py` | Single source of truth: the wire **classes** + default plug/switch/socket compatibility rules + `classify()`. |
| `export_products.py` | Read-only dump of all Wire products → `wire_products_all.json` (for offline work / inspection). |
| `derive_catalog.py` | Pure builder: raw products → `cordsets.catalog.json` (each wire gets a `classId`; each component its `compatClasses`). Importable + CLI. |
| `sync_catalog.py` | **Scheduled/prod entry:** live-fetch Wire products → build → write `cordsets.catalog.json`. Applies compat overrides if present. |
| `make_compat_csv.py` | Generate `hardware_compat.csv` for Ian to verify (components × wire classes). |
| `import_compat_csv.py` | Ian's edited CSV → `compat_overrides.json` (folded into the next build). |

Generated (not hand-edited): `cordsets.catalog.json`, `compat_overrides.json`,
`hardware_compat.csv`, `wire_products_all.json`.

The Wire store is reached via `greenlight.shopify_client.get_wire_shopify_session()`
(needs `SHOPIFY_WIRE_*` in the repo `.env`). Run scripts with the repo venv:
`venv/bin/python tools/wire/cordset/<script>.py`.

## Common workflows

**Update hardware compatibility** (Ian changes what fits what):
1. Edit the cell(s) in `hardware_compat.csv` — keep it in sync with Ian's Google Sheet
   (his sheet is the human master; this CSV is what the importer reads).
2. `venv/bin/python tools/wire/cordset/import_compat_csv.py`  → `compat_overrides.json`
3. `venv/bin/python tools/wire/cordset/sync_catalog.py`       → catalog (`compatSource: verified-overrides`),
   published live — the store picks it up within minutes, no deploy (or just wait for
   the hourly timer).
Never hand-edit `compat_overrides.json` — the next CSV import overwrites it.

**Refresh the catalog** (new wire colors, price/stock changes, new products):
automatic — `cordset-catalog-sync.timer` runs `sync_catalog.py` hourly, which publishes
to `/var/www/cordset/` (nginx: `https://greenlight.sundialwire.com/cordset/cordsets.catalog.json`,
see `services/nginx-cordset-catalog.conf`). The storefront builder loads that live copy,
so no deploy is needed. The catalog bundled in the app is only the fallback (live copy
unreachable / slow); `npm run deploy` in the app repo refreshes it from the live copy.
(New wire SKUs classify automatically; a genuinely new construction lands in
`diagnostics.droppedUnclassified` — extend `classify()` + `WIRE_CLASSES` in `classes.py`.)

**Iterate on the UI** (layout, behavior, copy):
Not here — edit `extensions/cordset-configurator/` in `~/projects/sundial-cordsets`
directly, then `npm run deploy` there (see its CLAUDE.md).

**Add a new wire class** (e.g. a new construction Ian wants rated separately):
Add it to `WIRE_CLASSES` in `classes.py`, teach `classify()` how to route wires into
it, regenerate the CSV (`make_compat_csv.py`) for Ian, then run the compat workflow.

## Wire classes & compatibility model

Compatibility is a property of the wire **class** (gauge / conductors / construction),
not the individual color — so `hardware_compat.csv` is one row per component × the
wire classes as columns. `classify()` maps each wire to a class; `compatClasses` on
each component lists the classes it fits (default rules in `classes.py`, overridden
per-variant by Ian's CSV). The form gates on `wire.classId ∈ component.compatClasses`.

## Deploy target & preview surface

App: `sundial-cordsets` on the `sundial-wire` store (org 186855317). The block is
"Cord Set Builder" — added to a page via an OS 2.0 JSON template + a host section that
accepts `@app` blocks. Settings: paper background, constrain width, and an optional
**labor product** override.

The **assembly fee** is a real Shopify product resolved by variant SKU `ASSEMBLY`
(`LABOR_SKU` in `derive_catalog.py`) during the catalog build, so its price is whatever
Shopify says (currently $10.00) and a price change flows through the next sync. It rides
as its own cart line per cord set; the bench work order hides it by that same SKU. The
block's labor product setting overrides it; if no ACTIVE `ASSEMBLY` variant exists the
line is omitted and the sync prints a MISSING warning.
