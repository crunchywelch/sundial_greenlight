# Admin Cable Management — Overhaul Roadmap

Status: **proposed**. Nothing in the current admin cable UI is in production use, so this
is a free-hand rebuild rather than a migration.

## The problem with what's there now

`app.assign.jsx` (323 lines) is organized around a **verb**, not an object. It can assign a
cable to a customer and nothing else — there is no unassign anywhere in the admin, and no
page that shows a single cable. Every action we add (unassign, dealer assign, clear code,
generate code) would either bolt another mode onto that page or spawn its own verb-route,
leaving four routes each owning a slice of one cable's state.

Key the UI on the **cable** instead and every action becomes a button on one page, with the
operator able to see current state before mutating it.

### Salvage from `app.assign.jsx`
- `searchCustomer` — extract as a reusable picker; the company picker needs the same shape.
- Scanner integration (`scannerActive` + the MQTT bridge via `api.scanner-events.jsx`) —
  the hard-won part, and it works. Becomes the lookup box on the detail page.
- The `assign` action — unchanged, just one action among several.
- `searchCable` — keep the idea, rewrite the query (see Phase 0).

### Do not carry forward
- **The N+1 customer lookup** (`app.assign.jsx:81-97`): one `getCustomer` GraphQL call per
  result row, up to 20. This is exactly what commit `21d303de` fixed on the cables-by-group
  page. It gets worse on a cable list that must also resolve a company per row.
- **`ILIKE '%term%'` on `serial_number`**: serials are exact identifiers, so this is a full
  table scan to find something directly addressable.

---

## Phase 0 — Foundations (before any UI)

Do these first. Everything after writes through them.

### 0a. Audit trail — `cable_events`
There is no history anywhere. Every mutation overwrites in place, unrecoverably. That was
tolerable when the only way to change a cable was standing at the bench in Greenlight with
the cable in hand; it stops being tolerable the moment these mutations are a web form that
more people can reach with less context.

A code review of the Phase A work found a mutation that silently destroyed dealer
attribution — nobody would have noticed for months. That class of bug is why this comes
first, not last.

```sql
CREATE TABLE cable_events (
    id BIGSERIAL PRIMARY KEY,
    serial_number TEXT NOT NULL REFERENCES audio_cables(serial_number),
    event TEXT NOT NULL,           -- assigned_customer, unassigned_customer,
                                   -- assigned_dealer, unassigned_dealer,
                                   -- code_generated, code_cleared, re_registered, qc_tested
    actor TEXT,                    -- operator initials, or 'admin:<staff email>'
    detail JSONB,                  -- {from: ..., to: ...}
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ON cable_events(serial_number, created_at DESC);
```

Write a `record_cable_event()` helper on both sides (Python in `greenlight/db.py`, JS in
`shopify_app/app/`) and call it from every mutation as it's built. Retrofitting history
later gives you no history for the window you most need it.

### 0b. One shared cable-state serializer
Greenlight and the admin currently each assemble their own view of a cable. They will
drift. Define one shape — identity, QC, commercial state — and derive both from it.
`greenlight/screens/cable.py:build_cable_info_panel` is the de-facto spec today.

### 0c. Fix the lookup primitives
- Serial search: exact match, prefix-match fallback. Not `ILIKE '%…%'`.
- Batch the customer and company lookups. One query for all GIDs on the page, not one per
  row. Follow `21d303de`.

---

## Phase 1 — Cable detail page (read-only)

Route keyed on serial, e.g. `app.cables.serial.$serial.jsx`. Read-only on purpose: useful
and safe immediately, and it makes Phase 2 a matter of adding buttons to a page that
already renders correct state.

Port the information architecture from `build_cable_info_panel`:

- **Identity** — serial, variant SKU, series, length, connector, finish, description
- **QC** — pass/fail, resistance values, tested date, operator
- **Commercial** — owner, dealer, order, registration code, registered date
- **Links** — customer, Shopify order, dealer, LTD edition
- **History** — the `cable_events` feed from 0a

Lookup box at the top accepting a typed serial *or* a live scan relayed from Greenlight
over MQTT.

---

## Phase 2 — Commercial mutations

**Depends on B0 (`read_companies` scope) and B2 (the B2B assign branch) from
`WHOLESALE_ATTRIBUTION.md`.**

Actions on the detail page:

- Assign / unassign customer
- Assign / unassign dealer, with a company picker
- Generate / clear registration code

### The rule that matters most
A cable can hold an owner **and** a dealer at once — sold to Mill River Music, then
registered by the buyer who bought it there. **Never render a single "Unassign" button.**
When both are set the UI must name both and make the operator choose which to release.
Mirror `greenlight/db.py:unassign_cable`, which takes an explicit `retail` / `wholesale`
channel and refuses to guess.

### Guards to carry over from Greenlight
- Refuse dealer-assign on a cable that already has an end owner (`already_registered`)
- Refuse clear-code on a dealer-sold cable — it would return a sold cable to retail
  inventory and double-sell it
- Re-register stays out of the admin: it changes what the cable physically *is*, and
  should require having it in hand

Every mutation writes a `cable_event`. Retire `app.assign.jsx` at the end of this phase.

---

## Phase 3 — Registration codes at scale

Today codes can only be generated from Greenlight's wholesale batch screen, so making a
cable sellable wholesale requires being at the bench with the Pi. Lift that:

- Generate a code for a single cable from its detail page
- Bulk-generate for a selected set (the wholesale batch screen, minus the bench)
- Show the code and its registration URL so it can be reprinted from anywhere

Label printing itself stays on the Pi (TSC printer). A print-queue that Greenlight drains
is a possible later addition, not part of this.

---

## Phase 4 — Dealer views

This is where the attribution work pays off. Without it the data is captured and never
seen.

- Company index — every B2B company, cable counts
- Company detail — the mirror of `app.customer.$id.cables.jsx`: every cable sold to this
  dealer, split by **registered** vs **still on their shelf** (`registered_at IS NULL`)
- Bulk assign a set of cables to a dealer

`greenlight/db.py:get_cables_for_company` is the reference query.

---

## Phase 5 — Reporting and reconciliation

### Agree on the inventory buckets first
Three places already count cable state and they do not agree:
`util/audio/audio_sku_catalog_report.py`, the editions list (commit `167361ea`), and the
admin inventory page. In particular `wholesale` currently means "has a registration code",
which cannot distinguish a cable *allocated* for wholesale from one *actually sold* to a
dealer. Those are different numbers the moment dealer data starts flowing.

Proposed canonical set:

| bucket | predicate |
|---|---|
| untested | `test_passed IS NULL` |
| failed | `test_passed = FALSE` |
| available (retail) | passed, no owner, no code, no dealer |
| allocated (wholesale) | passed, has code, **no** dealer |
| sold to dealer | `wholesale_company_gid IS NOT NULL`, `registered_at IS NULL` |
| registered | `registered_at IS NOT NULL` |
| assigned (retail) | `shopify_gid` set with no dealer |

Define once, use everywhere, and update `audio_sku_catalog_report.py` to match.

---

## Stays in Greenlight

Hardware-bound to the bench, not candidates for the admin:

- QC testing (Arduino cable tester)
- Label printing (TSC printer)
- Registration intake scanning — though note scans are already bridged to the admin over
  MQTT, so admin-side *lookup* by scan is viable
- Re-register / SKU correction

## Suggested order of execution

Phase 0 and Phase 1 have no dependency on the in-flight Phase B work and can start
immediately. Phase 2 needs B0 and B2 landed. Phases 3–5 are independent of each other and
can be picked up by value.
