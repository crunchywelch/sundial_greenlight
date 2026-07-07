import { useEffect, useMemo, useState } from "react";
import { json } from "@remix-run/node";
import { useActionData, useLoaderData, useSubmit } from "@remix-run/react";
import { authenticate } from "../shopify.server";
import { query } from "../db.server";
import { parseVariantSku, formatVariantSku } from "../cable-config.server";

export async function loader({ request }) {
  await authenticate.admin(request);
  const url = new URL(request.url);
  const host = url.searchParams.get("host") || "";
  let adminPath = "";
  try {
    adminPath = atob(host);
  } catch (e) {}
  const appHandle = process.env.SHOPIFY_APP_HANDLE || "greenlight-2";
  return json({ adminPath, appHandle });
}

// Empty per-state tally, so accumulation never trips over undefined.
const emptyStates = () => ({ retail: 0, wholesale: 0, assigned: 0, failed: 0, untested: 0, total: 0 });

export async function action({ request }) {
  const { admin } = await authenticate.admin(request);
  const formData = await request.formData();
  const intent = formData.get("intent");

  if (intent === "fetch") {
    try {
      // One pass over audio_cables, bucketed into the five mutually-exclusive
      // lifecycle states (priority: assigned > wholesale > QC outcome). They
      // sum to `total`. "retail" is exactly what we push to Shopify — passed
      // QC, unassigned, not wholesale-allocated — so Shopify qty should match
      // it. LTD groups are merch-only (Editions tab), excluded here.
      const stateResult = await query(
        `SELECT sku_group, prefix, length, connector_code,
           COUNT(*) FILTER (WHERE shopify_gid IS NOT NULL AND shopify_gid != '') AS assigned,
           COUNT(*) FILTER (WHERE (shopify_gid IS NULL OR shopify_gid = '') AND registration_code IS NOT NULL) AS wholesale,
           COUNT(*) FILTER (WHERE (shopify_gid IS NULL OR shopify_gid = '') AND registration_code IS NULL AND test_passed = TRUE) AS retail,
           COUNT(*) FILTER (WHERE (shopify_gid IS NULL OR shopify_gid = '') AND registration_code IS NULL AND test_passed = FALSE) AS failed,
           COUNT(*) FILTER (WHERE (shopify_gid IS NULL OR shopify_gid = '') AND registration_code IS NULL AND test_passed IS NULL) AS untested,
           COUNT(*) AS total
         FROM audio_cables
         WHERE sku_group !~ '^LTD-'
         GROUP BY sku_group, prefix, length, connector_code`
      );

      // Accumulate (+=), not assign. MISC groups collapse multiple
      // (length, connector_code) rows onto the same variant SKU; this sums them.
      const byVariant = {};
      const groupBySku = {};
      for (const row of stateResult.rows) {
        const variantSku = formatVariantSku({
          prefix: row.prefix,
          group_sku: row.sku_group,
          length: Number(row.length),
          connector_code: row.connector_code,
        });
        if (!variantSku) continue;
        const acc = (byVariant[variantSku] ||= emptyStates());
        acc.retail += parseInt(row.retail);
        acc.wholesale += parseInt(row.wholesale);
        acc.assigned += parseInt(row.assigned);
        acc.failed += parseInt(row.failed);
        acc.untested += parseInt(row.untested);
        acc.total += parseInt(row.total);
        groupBySku[variantSku] = row.sku_group;
      }

      // Current Shopify quantities, keyed by SKU.
      const shopifyInventory = {};
      let hasNextPage = true;
      let cursor = null;
      while (hasNextPage) {
        const response = await admin.graphql(
          `#graphql
          query getProducts($cursor: String) {
            products(first: 50, after: $cursor) {
              pageInfo { hasNextPage endCursor }
              edges {
                node {
                  id title
                  variants(first: 100) {
                    edges { node { id sku inventoryQuantity title } }
                  }
                }
              }
            }
          }`,
          { variables: { cursor } }
        );
        const data = await response.json();
        if (data.errors) {
          console.error("GraphQL errors:", data.errors);
          break;
        }
        const products = data.data?.products;
        if (!products) break;
        for (const edge of products.edges) {
          const product = edge.node;
          const productNumericId = product.id?.split("/").pop() || null;
          for (const variantEdge of product.variants.edges) {
            const variant = variantEdge.node;
            if (variant.sku) {
              shopifyInventory[variant.sku] = {
                quantity: variant.inventoryQuantity,
                productTitle: product.title,
                variantTitle: variant.title,
                productNumericId,
              };
            }
          }
        }
        hasNextPage = products.pageInfo.hasNextPage;
        cursor = products.pageInfo.endCursor;
      }

      // LTD shouldn't appear at all; the DB query filters it, this catches any
      // LTD-shaped Shopify variant (e.g. a leftover test product).
      const isLtdSku = (s) => /(^|-)LTD-/.test(s);

      const allSkus = new Set([...Object.keys(byVariant), ...Object.keys(shopifyInventory)]);
      const inventory = [];
      for (const sku of allSkus) {
        if (isLtdSku(sku)) continue;
        const st = byVariant[sku] || emptyStates();
        const shop = shopifyInventory[sku] || { quantity: 0, productTitle: null, variantTitle: null, productNumericId: null };
        const parsed = parseVariantSku(sku);
        const diff = st.retail - shop.quantity; // + means DB has more sellable than Shopify shows
        inventory.push({
          sku,
          sku_group: groupBySku[sku] || (parsed.kind ? parsed.group_sku : null),
          retail: st.retail,
          wholesale: st.wholesale,
          assigned: st.assigned,
          failed: st.failed,
          untested: st.untested,
          total: st.total,
          shopifyCount: shop.quantity,
          diff,
          synced: diff === 0,
          productTitle: shop.productTitle,
          variantTitle: shop.variantTitle,
          productNumericId: shop.productNumericId,
        });
      }
      inventory.sort((a, b) => a.sku.localeCompare(b.sku));

      const summary = {
        skuCount: inventory.length,
        drifted: inventory.filter((r) => !r.synced).length,
        withFailures: inventory.filter((r) => r.failed > 0).length,
        withUntested: inventory.filter((r) => r.untested > 0).length,
        wholesaleUnits: inventory.reduce((n, r) => n + r.wholesale, 0),
      };
      return json({ inventory, summary });
    } catch (error) {
      console.error("Error fetching inventory:", error);
      return json({ error: "Failed to fetch inventory", message: error.message }, { status: 500 });
    }
  }

  if (intent === "sync") {
    try {
      // "Available" for the retail store excludes assigned cables (shopify_gid),
      // wholesale/reseller-allocated cables (registration_code), and LTD groups
      // (merch-only). Mirrors greenlight/db.py get_available_count_for_sku and
      // the Python reconcile so all inventory paths agree.
      const dbResult = await query(
        `SELECT sku_group, prefix, length, connector_code, COUNT(*) as count
         FROM audio_cables
         WHERE (shopify_gid IS NULL OR shopify_gid = '') AND registration_code IS NULL AND sku_group !~ '^LTD-'
         GROUP BY sku_group, prefix, length, connector_code
         ORDER BY sku_group, prefix, length, connector_code`
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

      const locationResponse = await admin.graphql(`{ locations(first: 1) { edges { node { id } } } }`);
      const locationData = await locationResponse.json();
      if (locationData.errors) {
        return json({ error: "GraphQL error fetching location", details: locationData.errors }, { status: 500 });
      }
      const locationId = locationData.data?.locations?.edges?.[0]?.node?.id;
      if (!locationId) return json({ error: "Could not find location" }, { status: 500 });

      const variantsBySku = {};
      let hasNextPage = true;
      let cursor = null;
      while (hasNextPage) {
        const response = await admin.graphql(
          `#graphql
          query getProductVariants($cursor: String) {
            productVariants(first: 100, after: $cursor) {
              pageInfo { hasNextPage endCursor }
              edges {
                node { id sku inventoryItem { id } inventoryQuantity }
              }
            }
          }`,
          { variables: { cursor } }
        );
        const data = await response.json();
        if (data.errors) break;
        const variants = data.data?.productVariants;
        if (!variants) break;
        for (const edge of variants.edges) {
          const variant = edge.node;
          if (variant.sku && variant.inventoryItem?.id) {
            variantsBySku[variant.sku] = {
              variantId: variant.id,
              inventoryItemId: variant.inventoryItem.id,
              currentQuantity: variant.inventoryQuantity,
            };
          }
        }
        hasNextPage = variants.pageInfo.hasNextPage;
        cursor = variants.pageInfo.endCursor;
      }

      // Iterate Shopify-side catalog and MISC variants and reconcile to
      // dbCount, defaulting to 0 for sold-out variants. LTD groups are
      // merch-only — not website inventory — so we skip them entirely.
      const results = [];
      const skusToSync = Object.keys(variantsBySku).filter((sku) => {
        const kind = parseVariantSku(sku).kind;
        return kind !== null && kind !== "ltd";
      });

      for (const sku of skusToSync) {
        const dbCount = dbInventory[sku] ?? 0;
        const variantInfo = variantsBySku[sku];
        if (variantInfo.currentQuantity === dbCount) {
          results.push({ sku, status: "unchanged", quantity: dbCount });
          continue;
        }
        try {
          const setResponse = await admin.graphql(
            `#graphql
            mutation inventorySetQuantities($input: InventorySetQuantitiesInput!) {
              inventorySetQuantities(input: $input) {
                inventoryAdjustmentGroup { reason }
                userErrors { field message }
              }
            }`,
            {
              variables: {
                input: {
                  name: "available",
                  reason: "correction",
                  ignoreCompareQuantity: true,
                  quantities: [{ inventoryItemId: variantInfo.inventoryItemId, locationId, quantity: dbCount }],
                },
              },
            }
          );
          const setData = await setResponse.json();
          if (setData.data?.inventorySetQuantities?.userErrors?.length > 0) {
            results.push({ sku, status: "error", error: setData.data.inventorySetQuantities.userErrors[0].message });
          } else {
            results.push({ sku, status: "synced", from: variantInfo.currentQuantity, to: dbCount });
          }
        } catch (err) {
          results.push({ sku, status: "error", error: err.message });
        }
      }

      const synced = results.filter((r) => r.status === "synced").length;
      const unchanged = results.filter((r) => r.status === "unchanged").length;
      const skipped = results.filter((r) => r.status === "skipped").length;
      const errors = results.filter((r) => r.status === "error").length;
      return json({ syncResults: { synced, unchanged, skipped, errors, details: results } });
    } catch (error) {
      console.error("Error syncing inventory:", error);
      return json({ error: "Failed to sync inventory", message: error.message }, { status: 500 });
    }
  }

  return json({ error: "Invalid intent" }, { status: 400 });
}

// State filter predicates for the toolbar dropdown.
const STATE_FILTERS = {
  all: { label: "All states", test: () => true },
  retail: { label: "Has retail stock", test: (r) => r.retail > 0 },
  wholesale: { label: "Has wholesale", test: (r) => r.wholesale > 0 },
  failed: { label: "Has failed QC", test: (r) => r.failed > 0 },
  untested: { label: "Has untested", test: (r) => r.untested > 0 },
  drifted: { label: "Out of sync", test: (r) => !r.synced },
};

export default function Inventory() {
  const submit = useSubmit();
  const actionData = useActionData();
  const { adminPath, appHandle } = useLoaderData();

  const [inventory, setInventory] = useState([]);
  const [summary, setSummary] = useState(null);
  const [syncResults, setSyncResults] = useState(null);
  const [filter, setFilter] = useState("");
  const [stateFilter, setStateFilter] = useState("all");

  const filterLower = filter.trim().toLowerCase();
  const filteredInventory = useMemo(() => {
    const pred = STATE_FILTERS[stateFilter]?.test || (() => true);
    return inventory.filter(
      (item) =>
        pred(item) &&
        (!filterLower ||
          item.sku.toLowerCase().includes(filterLower) ||
          (item.productTitle || "").toLowerCase().includes(filterLower) ||
          (item.variantTitle || "").toLowerCase().includes(filterLower))
    );
  }, [inventory, filterLower, stateFilter]);

  useEffect(() => {
    if (actionData?.inventory) setInventory(actionData.inventory);
    if (actionData?.summary) setSummary(actionData.summary);
  }, [actionData?.inventory, actionData?.summary]);

  useEffect(() => {
    if (actionData?.syncResults) setSyncResults(actionData.syncResults);
  }, [actionData?.syncResults]);

  const refetch = () => {
    const fd = new FormData();
    fd.append("intent", "fetch");
    submit(fd, { method: "post" });
  };

  // Auto-fetch on mount.
  useEffect(() => {
    refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // After a sync, re-fetch so the table shows the new Shopify quantities.
  useEffect(() => {
    if (!actionData?.syncResults) return;
    refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actionData?.syncResults]);

  // Deep link into the per-cable drill-in, optionally pre-filtered by state.
  const drillUrl = (skuGroup, state) => {
    if (!skuGroup) return "#";
    const base = `https://${adminPath}/apps/${appHandle}/app/cables/${encodeURIComponent(skuGroup)}`;
    return state ? `${base}?state=${state}` : base;
  };

  return (
    <div style={{ padding: "0 20px 20px", maxWidth: "1280px", margin: "0 auto", fontFamily: "system-ui, -apple-system, sans-serif" }}>
      <h1 style={{ fontSize: "24px", marginBottom: "6px" }}>Inventory Hub</h1>
      <p style={{ margin: "0 0 16px", color: "#666" }}>
        Every cable by lifecycle state, per SKU. <strong>Retail</strong> is what we sell on shopify.com and push as the
        Shopify quantity; live edits and the nightly reconcile keep the two aligned — the <strong>Sync</strong> column is a
        health check, and the button below is a manual fallback.
      </p>

      {summary && <SummaryChips summary={summary} />}

      <div style={{ border: "1px solid #ddd", borderRadius: "8px", padding: "20px", backgroundColor: "#fff" }}>
        <div style={{ display: "flex", gap: "10px", alignItems: "center", marginBottom: "16px", flexWrap: "wrap" }}>
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter by SKU or product…"
            style={{ flex: "1 1 220px", padding: "8px 10px", border: "1px solid #ccc", borderRadius: "4px", fontSize: "14px" }}
          />
          <select
            value={stateFilter}
            onChange={(e) => setStateFilter(e.target.value)}
            style={{ padding: "8px 10px", border: "1px solid #ccc", borderRadius: "4px", fontSize: "14px" }}
          >
            {Object.entries(STATE_FILTERS).map(([key, { label }]) => (
              <option key={key} value={key}>{label}</option>
            ))}
          </select>
          <span style={{ fontSize: "13px", color: "#666", whiteSpace: "nowrap" }}>
            {filterLower || stateFilter !== "all"
              ? `${filteredInventory.length} of ${inventory.length}`
              : `${inventory.length} variants`}
          </span>
          <button onClick={refetch} style={btn("#008060")}>Refresh</button>
          <button
            onClick={() => {
              if (confirm("Force-sync Shopify inventory to match retail (unassigned, non-wholesale) cable counts?")) {
                const fd = new FormData();
                fd.append("intent", "sync");
                submit(fd, { method: "post" });
              }
            }}
            style={btn("#5c6ac4")}
          >
            Force sync
          </button>
        </div>

        {syncResults && <SyncBanner syncResults={syncResults} onDismiss={() => setSyncResults(null)} />}

        {inventory.length === 0 ? (
          <div style={{ padding: "40px", textAlign: "center", color: "#666" }}>Loading inventory data…</div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "14px" }}>
              <thead>
                <tr style={{ backgroundColor: "#f5f5f5" }}>
                  <th style={thL}>SKU</th>
                  <th style={thL}>Product</th>
                  <th style={thR} title="Passed QC, unassigned, not wholesale — sellable on shopify.com">Retail</th>
                  <th style={thR} title="Reg-coded, allocated to a reseller">Wholesale</th>
                  <th style={thR} title="Shipped to a customer">Assigned</th>
                  <th style={thR} title="Failed QC">Failed</th>
                  <th style={thR} title="Registered but not yet tested">Untested</th>
                  <th style={thR}>Total</th>
                  <th style={thR}>Shopify</th>
                  <th style={thR}>Sync</th>
                </tr>
              </thead>
              <tbody>
                {filteredInventory.map((item) => {
                  const rowBg = !item.synced ? "#fffbeb" : item.failed > 0 ? "#fff5f5" : "#fff";
                  return (
                    <tr key={item.sku} style={{ backgroundColor: rowBg }}>
                      <td style={{ ...tdL, fontWeight: "bold" }}>
                        <a href={drillUrl(item.sku_group)} target="_top" style={linkStyle}>{item.sku}</a>
                      </td>
                      <td style={{ ...tdL, color: "#666" }}>
                        {item.productTitle || <span style={{ color: "#c00" }}>— no product —</span>}
                        {item.variantTitle && item.variantTitle !== "Default Title" && (
                          <span style={{ color: "#999" }}> / {item.variantTitle}</span>
                        )}
                      </td>
                      <NumCell n={item.retail} strong color="#008060" />
                      <NumCell n={item.wholesale} color="#5c3d99" href={item.wholesale > 0 ? drillUrl(item.sku_group, "wholesale") : null} />
                      <NumCell n={item.assigned} color="#1a3d7c" href={item.assigned > 0 ? drillUrl(item.sku_group, "assigned") : null} />
                      <NumCell n={item.failed} color="#d72c0d" href={item.failed > 0 ? drillUrl(item.sku_group, "failed") : null} />
                      <NumCell n={item.untested} color="#bf5000" href={item.untested > 0 ? drillUrl(item.sku_group, "untested") : null} />
                      <NumCell n={item.total} color="#333" />
                      <NumCell n={item.shopifyCount} color="#333" />
                      <td style={{ ...tdR }}>
                        {item.synced ? (
                          <span style={{ color: "#008060", fontWeight: "bold" }}>OK</span>
                        ) : (
                          <span style={{ color: "#d72c0d", fontWeight: "bold" }} title={`Retail ${item.retail} vs Shopify ${item.shopifyCount}`}>
                            {item.diff > 0 ? "+" : ""}{item.diff}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {filteredInventory.length === 0 && (
              <div style={{ padding: "20px", textAlign: "center", color: "#666", fontSize: "14px" }}>
                No variants match the current filters.
              </div>
            )}

            <div style={{ marginTop: "20px", padding: "15px", backgroundColor: "#f5f5f5", borderRadius: "4px", fontSize: "13px", color: "#666", lineHeight: 1.6 }}>
              <strong>States</strong> (each cable counts once; they sum to Total):
              {" "}<b style={{ color: "#008060" }}>Retail</b> = sellable on shopify.com ·
              {" "}<b style={{ color: "#5c3d99" }}>Wholesale</b> = reg-coded, reseller-allocated ·
              {" "}<b style={{ color: "#1a3d7c" }}>Assigned</b> = shipped to a customer ·
              {" "}<b style={{ color: "#d72c0d" }}>Failed</b> / <b style={{ color: "#bf5000" }}>Untested</b> = stuck in QC.
              {" "}<b>Sync</b> compares Retail to the live Shopify quantity. Click any non-zero count to drill into that SKU's cables.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function SummaryChips({ summary }) {
  const chips = [
    { label: "SKUs", value: summary.skuCount, color: "#333" },
    { label: "Out of sync", value: summary.drifted, color: summary.drifted > 0 ? "#d72c0d" : "#008060" },
    { label: "SKUs w/ failed QC", value: summary.withFailures, color: summary.withFailures > 0 ? "#d72c0d" : "#666" },
    { label: "SKUs w/ untested", value: summary.withUntested, color: summary.withUntested > 0 ? "#bf5000" : "#666" },
    { label: "Wholesale units", value: summary.wholesaleUnits, color: "#5c3d99" },
  ];
  return (
    <div style={{ display: "flex", gap: "12px", flexWrap: "wrap", marginBottom: "16px" }}>
      {chips.map((c) => (
        <div key={c.label} style={{ border: "1px solid #eee", borderRadius: "8px", padding: "10px 16px", backgroundColor: "#fff", minWidth: "110px" }}>
          <div style={{ fontSize: "22px", fontWeight: "bold", color: c.color }}>{c.value}</div>
          <div style={{ fontSize: "12px", color: "#666" }}>{c.label}</div>
        </div>
      ))}
    </div>
  );
}

function SyncBanner({ syncResults, onDismiss }) {
  const updated = syncResults.details?.filter((d) => d.status === "synced") || [];
  const errored = syncResults.details?.filter((d) => d.status === "error") || [];
  return (
    <div style={{ marginBottom: "20px", padding: "15px", backgroundColor: "#f0f9ff", border: "1px solid #b3d9ff", borderRadius: "4px", position: "relative" }}>
      <button onClick={onDismiss} aria-label="Dismiss" style={{ position: "absolute", top: "8px", right: "8px", background: "none", border: "none", cursor: "pointer", fontSize: "18px", color: "#666", padding: "4px 8px", lineHeight: 1 }}>×</button>
      <div style={{ fontWeight: "bold", marginBottom: "10px" }}>Sync Complete</div>
      <div style={{ display: "flex", gap: "20px", flexWrap: "wrap", fontSize: "14px" }}>
        <span style={{ color: "#008060" }}>Synced: {syncResults.synced}</span>
        <span style={{ color: "#666" }}>Unchanged: {syncResults.unchanged}</span>
        <span style={{ color: "#bf5000" }}>Skipped: {syncResults.skipped}</span>
        {syncResults.errors > 0 && <span style={{ color: "#d72c0d" }}>Errors: {syncResults.errors}</span>}
      </div>
      {updated.length > 0 && (
        <div style={{ marginTop: "10px", fontSize: "13px", color: "#666" }}>
          <strong>Updated:</strong> {updated.map((d) => `${d.sku} (${d.from} → ${d.to})`).join(", ")}
        </div>
      )}
      {errored.length > 0 && (
        <div style={{ marginTop: "10px", fontSize: "13px", color: "#d72c0d" }}>
          <strong>Errors:</strong> {errored.map((d) => `${d.sku}: ${d.error}`).join(", ")}
        </div>
      )}
    </div>
  );
}

function NumCell({ n, color, strong, href }) {
  let content;
  if (n === 0) {
    content = <span style={{ color: "#ccc" }}>0</span>;
  } else if (href) {
    content = <a href={href} target="_top" style={{ color, fontWeight: strong ? "bold" : "600", textDecoration: "none" }}>{n}</a>;
  } else {
    content = <span style={{ color, fontWeight: strong ? "bold" : "normal" }}>{n}</span>;
  }
  return <td style={tdR}>{content}</td>;
}

const btn = (bg) => ({ padding: "8px 16px", backgroundColor: bg, color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer", fontSize: "14px", whiteSpace: "nowrap" });
const linkStyle = { color: "#008060", textDecoration: "none" };
const thL = { padding: "12px", textAlign: "left", borderBottom: "2px solid #ddd" };
const thR = { padding: "12px", textAlign: "right", borderBottom: "2px solid #ddd" };
const tdL = { padding: "12px", borderBottom: "1px solid #eee" };
const tdR = { padding: "12px", borderBottom: "1px solid #eee", textAlign: "right" };
