# Wholesale Dealer Attribution (Shopify B2B)

Status: **Phase A landed** (commit `5b3be3d2`, Greenlight side). **Phase B pending**
(Shopify app + extension). This document is the handoff for Phase B.

## Why this exists

We sell cables wholesale to stores. A wholesale cable gets a `registration_code`, which
pulls it out of shopify.com retail availability, ships to the store, and the end buyer
later registers it at `sundialaudio.com/register`. That registration writes the buyer into
`audio_cables.shopify_gid`.

Until now nothing recorded **which store sold the cable**, so the dealer relationship was
lost the moment the end buyer registered. Shopify B2B is now enabled, and B2B orders carry
the company natively, so attribution can be captured automatically at fulfillment time
with no operator data entry.

## The invariant — read this before touching any assignment code

| column | meaning | written by |
|---|---|---|
| `shopify_gid` | **the end owner, always** | retail order fulfillment, or end-buyer registration |
| `wholesale_company_gid` | the B2B dealer that bought it | B2B order fulfillment only |
| `wholesale_location_gid` | that dealer's specific location | B2B order fulfillment only |
| `registered_at` | when the end buyer registered (warranty start) | end-buyer registration |

**A B2B order assignment must leave `shopify_gid` NULL.**

### The trap

This is the part that is easy to get wrong, because every neighbouring line of code does
the opposite. `handleAssignCable` in `shopify_app/app/routes/api.order-fulfillment.jsx`
currently writes:

```js
SET shopify_gid = $1, shopify_order_gid = $2   // $1 = customerId
```

On a **B2B** order that `customerId` is the *company contact* (a real Shopify customer —
e.g. "Testy McTest" is the contact for Testy Test Industries). If you write it into
`shopify_gid`, then `api.register-cable.jsx` rejects the end buyer, because both its GET
loader and its POST action 409 on any non-empty `shopify_gid`:

```js
if (row.shopify_gid && row.shopify_gid !== "") {
  return json({ error: "This cable has already been registered", code: "ALREADY_REGISTERED" }, { status: 409 });
}
```

The buyer scans the QR on their registration label and is told the cable is already
registered. Nothing errors on our side; it just silently fails for the customer.

Keeping `shopify_gid` NULL for B2B means that guard stays exactly as written and becomes
semantically correct — do **not** loosen it.

## Established facts (verified live, 2026-08-30)

- Two companies exist:
  - `gid://shopify/Company/3524034643` — Testy Test Industries
    - `gid://shopify/CompanyLocation/4596891731` — 349 Montrose Ave
  - `gid://shopify/Company/3524296787` — Mill River Music
    - `gid://shopify/CompanyLocation/4597153875` — 135 King St
- Order **#1006** is a real B2B order and returns `purchasingEntity.__typename ==
  "PurchasingCompany"` with company + location + contact. Every retail order returns
  `"Customer"`. That is a free, reliable retail-vs-wholesale discriminator — use it rather
  than inventing a flag.
- ⚠️ **`read_companies` is NOT in `shopify_app/shopify.app.toml` `[access_scopes]`.**
  Greenlight queries companies fine because it uses a client-credentials token, but the
  Remix app and the admin extension authenticate with the OAuth session token scoped by
  that file. **Add the scope and reinstall before B1**, or `purchasingEntity` comes back
  null and every order silently looks like retail — which lands you straight in the trap
  above.
- Current data: 43 cables carry a registration code, 41 with no `shopify_gid`. Nothing to
  backfill; the 2 assigned ones are Testy McTest test data.

## Phase A — already landed, do not redo

Commit `5b3be3d2`. Schema migration is already applied on the host.

- `util/audio/schema.sql` — the three columns + `idx_audio_cables_wholesale_company`.
- `greenlight/db.py`
  - `get_audio_cable` selects the new columns.
  - `unassign_cable` releases **either** channel and returns `channel: 'retail'|'wholesale'`.
    It clears `registered_at` alongside the owner. This is the escape hatch for a
    mis-assigned dealer cable.
  - `get_cables_for_company(company_gid)` — dealer cables never appear in
    `get_cables_for_customer`, since a B2B sale leaves `shopify_gid` NULL.
  - `assign_cable_to_order` / `force_assign_cable_to_order` take optional
    `company_gid` / `location_gid` and branch exactly as Phase B should. **Mirror this
    branch in the JS**; these are the reference implementation.
- `greenlight/screens/cable.py` — `is_committed = is_assigned or sold_to_dealer` gates
  assign / unassign / re-register, and clear-reg-code is refused on a dealer-sold cable
  (it would return a sold cable to retail inventory and double-sell it).

## Phase B — to do

### B0. App scopes (blocking prerequisite)
Add `read_companies` to `[access_scopes]` in `shopify_app/shopify.app.toml`, redeploy,
reinstall. Verify `purchasingEntity` is non-null on order #1006 before proceeding.

### B1. Capture the company in the admin extension
`shopify_app/extensions/order-fulfillment/src/BlockExtension.jsx`

Add to the order GraphQL query (the one that currently pulls `customer { id }`):

```graphql
purchasingEntity {
  __typename
  ... on PurchasingCompany {
    company  { id name }
    location { id name }
  }
}
```

Hold `companyId` / `companyLocationId` / `companyName` in state alongside the existing
`customerId`, and include them in the `assignCable` POST body. Render a badge
(`B2B · Mill River Music`) so the operator can see the order is wholesale.

**Gotcha:** `assignCable` currently bails early on a missing customer:

```js
if (!orderId || !customerId) {
  showBanner("warning", "Order has no customer assigned");
  return;
}
```

A B2B order usually *does* populate `order.customer` with the company contact, so this
probably passes — but it must not be what gates the assign. Change the condition to
`!orderId || (!customerId && !companyId)`, or a company-only order silently refuses to
take scans.

### B2. Branch the write
`shopify_app/app/routes/api.order-fulfillment.jsx`

- `handleAssignCable` — accept `companyId` / `companyLocationId`. When `companyId` is
  present: set `wholesale_company_gid`, `wholesale_location_gid`, `shopify_order_gid`, and
  **leave `shopify_gid` alone**. Otherwise keep today's retail behavior. The
  `serialNumber, orderId, customerId are required` guard needs relaxing — a B2B assign has
  no customer.
- Refuse a B2B assign when `cable.shopify_gid` is already set: that cable is registered to
  an end owner and must not be sold to a dealer. (Python equivalent returns
  `error: 'already_registered'`.)
- `handleUnassignCable` — also NULL both wholesale columns.
- `handleLookupCable` and the order-cables loader — select the new columns. The loader
  keys on `shopify_order_gid`, so it keeps working unchanged with `shopify_gid` NULL.

### B3. Registration endpoint
`shopify_app/app/routes/api.register-cable.jsx`

- POST UPDATE: add `registered_at = NOW()`.
- **Leave both `ALREADY_REGISTERED` guards untouched.**
- Optional: have the GET loader return the dealer name so the registration page can say
  "purchased from Mill River Music".

### B4. Company name lookup — Greenlight side, coordinate before starting
`greenlight/shopify_client.py` needs `get_company_by_id()` / `list_companies()`, and
`build_cable_info_panel` in `greenlight/screens/cable.py` currently prints the raw company
GID in its `🏪 Sold via:` block pending that lookup. Cache the lookup module-level — the
panel re-renders on every iteration of `cable_action_loop`.

Proven query shape:

```graphql
{ companies(first: 100) { edges { node {
    id name
    locations(first: 10) { edges { node { id name } } }
} } } }
```

## Verification

1. After reinstall, `purchasingEntity` is non-null on order #1006.
2. Create a B2B draft order for Mill River Music containing a coded cable's SKU. Scan the
   cable onto it. Row must show: wholesale columns set, `shopify_order_gid` set,
   **`shopify_gid` still NULL**.
3. **The bug fix**: `GET /api/register-cable?code=<that cable's code>` returns the cable,
   **not** 409 `ALREADY_REGISTERED`. POST a registration; confirm `shopify_gid` and
   `registered_at` fill in while `wholesale_company_gid` survives unchanged.
4. Retail unaffected: scan a cable onto an ordinary (non-B2B) order — `shopify_gid` set,
   wholesale columns NULL.
5. Inventory: `get_available_count_for_sku` already excludes anything with a
   `registration_code`, so retail availability should be unmoved by the B2B sale.

## Follow-ups, not in scope

- Dealer-facing reporting ("cables sold to Mill River Music; how many registered").
  `get_cables_for_company` is the building block — `registered_at IS NULL` means the cable
  is still on the dealer's shelf.
- `custom.band_company` (a customer metafield) is unrelated to any of this. Leave it alone.
