# Cord Set Configurator

Customer-facing cord set / pendant builder for the **Sundial Wire** storefront.
Customers pick a wire, terminate each end (plug / socket / switch), and the exact
Shopify component variants are added to their cart.

## Architecture (the important part)

- **No backend.** The configurator is a **theme app extension** (an app block) in a
  separate Shopify app. It reads a catalog file and calls the storefront
  `/cart/add.js` directly — no server, no App Proxy, no draft orders.
- **Components-in-cart.** Each cord set adds its real component variants as separate
  cart lines — wire (`qty` = feet) + plug + optional socket + optional switch +
  optional labor product — bound by a `_cordset` line-item property. So Shopify
  decrements real inventory and prices are always the live Shopify prices.
- **The app repo is separate:** `~/projects/sundial-cordsets/` (its own git repo,
  extension-only app, installed on the `sundial-wire` store). The extension lives at
  `extensions/cordset-configurator/`. The tooling here (in greenlight) generates the
  extension's assets and the catalog it reads.

## Files here (`util/wire/cordset/`)

| File | Role |
|---|---|
| `classes.py` | Single source of truth: the wire **classes** + default plug/switch/socket compatibility rules + `classify()`. |
| `export_products.py` | Read-only dump of all Wire products → `wire_products_all.json` (for offline work / inspection). |
| `derive_catalog.py` | Pure builder: raw products → `cordsets.catalog.json` (each wire gets a `classId`; each component its `compatClasses`). Importable + CLI. |
| `sync_catalog.py` | **Scheduled/prod entry:** live-fetch Wire products → build → write `cordsets.catalog.json`. Applies compat overrides if present. |
| `make_compat_csv.py` | Generate `hardware_compat.csv` for Ian to verify (components × wire classes). |
| `import_compat_csv.py` | Ian's edited CSV → `compat_overrides.json` (folded into the next build). |
| `build_prototype.py` | **Shared UI source** (markup + CSS + JS `startCordset()`) + assembles the standalone Artifact demo `prototype.html`. |
| `build_extension.py` | Emits the real theme-extension files into the app repo from the shared source, incl. the live `/cart/add.js` bootstrap. |

Generated (not hand-edited): `cordsets.catalog.json`, `compat_overrides.json`,
`hardware_compat.csv`, `wire_products_all.json`, `prototype.html`.

The Wire store is reached via `greenlight.shopify_client.get_wire_shopify_session()`
(needs `SHOPIFY_WIRE_*` in the repo `.env`). Run scripts with the repo venv:
`venv/bin/python util/wire/cordset/<script>.py`.

## Common workflows

**Update hardware compatibility** (Ian changes what fits what):
1. Edit the cell(s) in `hardware_compat.csv` — keep it in sync with Ian's Google Sheet
   (his sheet is the human master; this CSV is what the importer reads).
2. `venv/bin/python util/wire/cordset/import_compat_csv.py`  → `compat_overrides.json`
3. `venv/bin/python util/wire/cordset/sync_catalog.py`       → catalog (`compatSource: verified-overrides`)
4. `venv/bin/python util/wire/cordset/build_extension.py`    → repackage into the app
5. `cd ~/projects/sundial-cordsets && shopify app deploy`
Never hand-edit `compat_overrides.json` — the next CSV import overwrites it.

**Refresh the catalog** (new wire colors, price/stock changes, new products):
`sync_catalog.py` → `build_extension.py` → `shopify app deploy`.
(New wire SKUs classify automatically; a genuinely new construction lands in
`diagnostics.droppedUnclassified` — extend `classify()` + `WIRE_CLASSES` in `classes.py`.)

**Iterate on the UI** (layout, behavior, copy):
Edit `build_prototype.py` (the shared markup/CSS/JS — it feeds both the demo and the
extension), then `build_prototype.py` (preview the Artifact) and `build_extension.py`
(update the app) → `shopify app deploy`. Sanity-check JS with
`node --check ~/projects/sundial-cordsets/extensions/cordset-configurator/assets/cordset.js`.

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
accepts `@app` blocks. Settings: paper background, constrain width, and the assembly
**labor product** (its variant/price/name feed the labor cart line; omit to skip labor).
