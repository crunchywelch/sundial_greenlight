import { json } from "@remix-run/node";
import { Form, Link, useActionData, useLoaderData, useLocation, useNavigation, useSearchParams } from "@remix-run/react";
import { authenticate } from "../shopify.server";
import { query } from "../db.server";
import { formatVariantSku, parseVariantSku } from "../cable-config.server";
import { listEditions } from "../editions.server";

export async function loader({ request }) {
  await authenticate.admin(request);
  const url = new URL(request.url);
  const filter = url.searchParams.get("filter") || "active";
  const editions = await listEditions(filter);
  return json({ editions, filter });
}

/**
 * Sync edition (LTD) variant inventory to Shopify. Sets each LTD variant's
 * available quantity to its sellable cable count: passed QC, unassigned
 * (no shopify_gid), and not wholesale-allocated. Variants with no sellable
 * stock are set to 0. LTD products are already tracked + DENY, so accurate
 * quantities make them stop selling once depleted.
 *
 * Mirrors the inventory page's sync (which deliberately excludes LTD).
 */
export async function action({ request }) {
  const { admin } = await authenticate.admin(request);
  const form = await request.formData();
  if (String(form.get("intent") || "") !== "sync") {
    return json({ error: "Invalid intent" }, { status: 400 });
  }

  // Sellable per LTD variant SKU. Multiple (length, connector) DB rows can map
  // to one variant SKU, so sum them.
  const dbResult = await query(
    `SELECT sku_group, prefix, length, connector_code, COUNT(*) AS count
       FROM audio_cables
      WHERE sku_group ~ '^LTD-'
        AND (shopify_gid IS NULL OR shopify_gid = '')
        AND registration_code IS NULL
        AND test_passed = TRUE
      GROUP BY sku_group, prefix, length, connector_code`
  );
  const dbInventory = {};
  for (const row of dbResult.rows) {
    const variantSku = formatVariantSku({
      prefix: row.prefix,
      group_sku: row.sku_group,
      length: Number(row.length),
      connector_code: row.connector_code,
    });
    if (variantSku) dbInventory[variantSku] = (dbInventory[variantSku] || 0) + parseInt(row.count);
  }

  const locResp = await admin.graphql(`{ locations(first: 1) { edges { node { id } } } }`);
  const locData = await locResp.json();
  const locationId = locData.data?.locations?.edges?.[0]?.node?.id;
  if (!locationId) return json({ error: "Could not find a Shopify location" }, { status: 500 });

  // All LTD variants in Shopify (SKU like {prefix}-{length}-LTD-{slug}{-R?}).
  const variantsBySku = {};
  let hasNextPage = true;
  let cursor = null;
  while (hasNextPage) {
    const resp = await admin.graphql(
      `#graphql
      query ltdVariants($cursor: String) {
        productVariants(first: 100, after: $cursor, query: "sku:*-LTD-*") {
          pageInfo { hasNextPage endCursor }
          edges { node { id sku inventoryItem { id } inventoryQuantity } }
        }
      }`,
      { variables: { cursor } }
    );
    const data = await resp.json();
    const variants = data.data?.productVariants;
    if (!variants) break;
    for (const edge of variants.edges) {
      const v = edge.node;
      if (v.sku && v.inventoryItem?.id && parseVariantSku(v.sku).kind === "ltd") {
        variantsBySku[v.sku] = { inventoryItemId: v.inventoryItem.id, currentQuantity: v.inventoryQuantity };
      }
    }
    hasNextPage = variants.pageInfo.hasNextPage;
    cursor = variants.pageInfo.endCursor;
  }

  const results = [];
  for (const sku of Object.keys(variantsBySku)) {
    const target = dbInventory[sku] ?? 0;
    const info = variantsBySku[sku];
    if (info.currentQuantity === target) {
      results.push({ sku, status: "unchanged", quantity: target });
      continue;
    }
    try {
      const setResp = await admin.graphql(
        `#graphql
        mutation setQty($input: InventorySetQuantitiesInput!) {
          inventorySetQuantities(input: $input) {
            userErrors { field message }
          }
        }`,
        {
          variables: {
            input: {
              name: "available",
              reason: "correction",
              ignoreCompareQuantity: true,
              quantities: [{ inventoryItemId: info.inventoryItemId, locationId, quantity: target }],
            },
          },
        }
      );
      const setData = await setResp.json();
      const errs = setData.data?.inventorySetQuantities?.userErrors || [];
      if (errs.length > 0) results.push({ sku, status: "error", error: errs[0].message });
      else results.push({ sku, status: "synced", from: info.currentQuantity, to: target });
    } catch (err) {
      results.push({ sku, status: "error", error: err.message });
    }
  }

  // Sellable DB stock with no matching Shopify variant: can't be synced (there's
  // nothing to set), so surface it — someone needs to add that variant online.
  for (const sku of Object.keys(dbInventory)) {
    if (dbInventory[sku] > 0 && !(sku in variantsBySku)) {
      results.push({ sku, status: "skipped", quantity: dbInventory[sku] });
    }
  }

  results.sort((a, b) => a.sku.localeCompare(b.sku));
  const count = (s) => results.filter((r) => r.status === s).length;
  return json({
    syncResults: {
      synced: count("synced"),
      unchanged: count("unchanged"),
      skipped: count("skipped"),
      errors: count("error"),
      details: results,
    },
  });
}

const TAB_STYLE_BASE = {
  padding: "8px 16px",
  border: "1px solid #ddd",
  borderRadius: "4px",
  cursor: "pointer",
  fontSize: "14px",
  textDecoration: "none",
  color: "#333",
  backgroundColor: "#fff",
};
const TAB_STYLE_ACTIVE = {
  ...TAB_STYLE_BASE,
  backgroundColor: "#008060",
  color: "#fff",
  border: "none",
  fontWeight: "bold",
};

export default function EditionsIndex() {
  const { editions, filter } = useLoaderData();
  const actionData = useActionData();
  const navigation = useNavigation();
  const syncing = navigation.state === "submitting";
  const sync = actionData?.syncResults;
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const linkTo = (pathname, extraParams = {}) => {
    const sp = new URLSearchParams(location.search);
    for (const [k, v] of Object.entries(extraParams)) sp.set(k, v);
    return { pathname, search: sp.toString() ? `?${sp.toString()}` : "" };
  };
  const qs = (f) => linkTo(location.pathname, { filter: f });

  return (
    <div style={{ padding: "20px", maxWidth: "1200px", margin: "0 auto", fontFamily: "system-ui, -apple-system, sans-serif" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
        <h1 style={{ fontSize: "24px", margin: 0 }}>Limited Editions</h1>
        <div style={{ display: "flex", gap: "10px" }}>
          <Form
            method="post"
            onSubmit={(e) => {
              if (!confirm("Set each edition variant's Shopify inventory to its sellable cable count (passed QC, unassigned, non-wholesale)? Sold-out variants are set to 0.")) {
                e.preventDefault();
              }
            }}
          >
            <input type="hidden" name="intent" value="sync" />
            <button
              type="submit"
              disabled={syncing}
              style={{
                padding: "10px 20px",
                backgroundColor: "#fff",
                color: "#008060",
                border: "1px solid #008060",
                borderRadius: "4px",
                fontSize: "14px",
                fontWeight: "bold",
                cursor: syncing ? "not-allowed" : "pointer",
              }}
            >
              {syncing ? "Syncing…" : "Sync inventory to Shopify"}
            </button>
          </Form>
          <Link
            to={linkTo("/app/editions/new")}
            style={{
              padding: "10px 20px",
              backgroundColor: "#008060",
              color: "#fff",
              border: "none",
              borderRadius: "4px",
              fontSize: "14px",
              fontWeight: "bold",
              textDecoration: "none",
            }}
          >
            + New Edition
          </Link>
        </div>
      </div>

      {actionData?.error && (
        <div style={{ padding: "12px 15px", backgroundColor: "#f8d7da", border: "1px solid #f5c6cb", borderRadius: "4px", marginBottom: "20px", color: "#721c24" }}>
          {actionData.error}
        </div>
      )}

      {sync && (() => {
        const warn = Boolean(sync.errors || sync.skipped);
        return (
          <div style={{ padding: "12px 15px", backgroundColor: warn ? "#fff3cd" : "#d4edda", border: `1px solid ${warn ? "#ffeeba" : "#c3e6cb"}`, borderRadius: "4px", marginBottom: "20px", color: warn ? "#856404" : "#155724" }}>
            <div style={{ fontWeight: "bold", marginBottom: sync.details.some((d) => d.status !== "unchanged") ? "8px" : 0 }}>
              Synced {sync.synced}, unchanged {sync.unchanged}
              {sync.skipped ? `, ${sync.skipped} not on Shopify` : ""}
              {sync.errors ? `, ${sync.errors} error${sync.errors === 1 ? "" : "s"}` : ""}.
            </div>
            {sync.details.filter((d) => d.status === "synced").map((d) => (
              <div key={d.sku} style={{ fontSize: "13px" }}>
                <code>{d.sku}</code>: {d.from} → {d.to}
              </div>
            ))}
            {sync.details.filter((d) => d.status === "skipped").map((d) => (
              <div key={d.sku} style={{ fontSize: "13px" }}>
                <code>{d.sku}</code>: {d.quantity} sellable, but no Shopify variant to sell it
              </div>
            ))}
            {sync.details.filter((d) => d.status === "error").map((d) => (
              <div key={d.sku} style={{ fontSize: "13px", color: "#721c24" }}>
                <code>{d.sku}</code>: {d.error}
              </div>
            ))}
          </div>
        );
      })()}

      <div style={{ display: "flex", gap: "10px", marginBottom: "20px" }}>
        <Link to={qs("active")} style={filter === "active" ? TAB_STYLE_ACTIVE : TAB_STYLE_BASE}>Active</Link>
        <Link to={qs("archived")} style={filter === "archived" ? TAB_STYLE_ACTIVE : TAB_STYLE_BASE}>Archived</Link>
        <Link to={qs("all")} style={filter === "all" ? TAB_STYLE_ACTIVE : TAB_STYLE_BASE}>All</Link>
      </div>

      {editions.length === 0 ? (
        <div style={{ padding: "40px", textAlign: "center", backgroundColor: "#f5f5f5", borderRadius: "8px", color: "#666" }}>
          {filter === "archived" ? "No archived editions." : filter === "active" ? "No active editions. Create one to get started." : "No editions yet."}
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "14px" }}>
            <thead>
              <tr style={{ backgroundColor: "#f5f5f5" }}>
                <th style={{ padding: "12px", textAlign: "left", borderBottom: "2px solid #ddd" }}>Slug</th>
                <th style={{ padding: "12px", textAlign: "left", borderBottom: "2px solid #ddd" }}>Description</th>
                <th style={{ padding: "12px", textAlign: "right", borderBottom: "2px solid #ddd" }}>Cables</th>
                <th style={{ padding: "12px", textAlign: "left", borderBottom: "2px solid #ddd" }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {editions.map((e) => (
                <tr key={e.sku} style={{ backgroundColor: e.active ? "#fff" : "#fafafa" }}>
                  <td style={{ padding: "12px", borderBottom: "1px solid #eee", fontWeight: "bold" }}>
                    <Link to={linkTo(`/app/cables/${encodeURIComponent(e.sku)}`)} style={{ color: "#008060", textDecoration: "none" }}>
                      {e.slug}
                    </Link>
                    <div style={{ fontSize: "12px", fontWeight: "normal", color: "#999" }}>{e.sku}</div>
                  </td>
                  <td style={{ padding: "12px", borderBottom: "1px solid #eee" }}>{e.description}</td>
                  <td style={{ padding: "12px", borderBottom: "1px solid #eee", textAlign: "right", fontWeight: "bold" }}>{e.cable_count}</td>
                  <td style={{ padding: "12px", borderBottom: "1px solid #eee" }}>
                    <span style={{
                      padding: "4px 8px",
                      borderRadius: "12px",
                      fontSize: "12px",
                      fontWeight: "bold",
                      backgroundColor: e.active ? "#d4edda" : "#e2e3e5",
                      color: e.active ? "#155724" : "#6c757d",
                    }}>
                      {e.active ? "Active" : "Archived"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
