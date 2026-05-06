import { useEffect, useState } from "react";
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

export async function action({ request }) {
  const { admin } = await authenticate.admin(request);
  const formData = await request.formData();
  const intent = formData.get("intent");

  if (intent === "fetch") {
    try {
      const totalResult = await query(
        `SELECT sku_group, length, connector_code, COUNT(*) as count
         FROM audio_cables
         GROUP BY sku_group, length, connector_code
         ORDER BY sku_group, length, connector_code`
      );
      // Accumulate (+=), not assign. For LTD/MISC groups multiple
      // (length, connector_code) rows collapse to the same variant SKU
      // (the group SKU itself), and we want their counts summed.
      const totalInventory = {};
      for (const row of totalResult.rows) {
        const variantSku = formatVariantSku({
          group_sku: row.sku_group,
          length: Number(row.length),
          connector_code: row.connector_code,
        });
        if (variantSku) totalInventory[variantSku] = (totalInventory[variantSku] || 0) + parseInt(row.count);
      }

      const dbResult = await query(
        `SELECT sku_group, length, connector_code, COUNT(*) as count
         FROM audio_cables
         WHERE shopify_gid IS NULL OR shopify_gid = ''
         GROUP BY sku_group, length, connector_code
         ORDER BY sku_group, length, connector_code`
      );
      const dbInventory = {};
      for (const row of dbResult.rows) {
        const variantSku = formatVariantSku({
          group_sku: row.sku_group,
          length: Number(row.length),
          connector_code: row.connector_code,
        });
        if (variantSku) dbInventory[variantSku] = (dbInventory[variantSku] || 0) + parseInt(row.count);
      }

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

      const allSkus = new Set([...Object.keys(totalInventory), ...Object.keys(dbInventory), ...Object.keys(shopifyInventory)]);
      const inventory = [];
      for (const sku of allSkus) {
        const totalCount = totalInventory[sku] || 0;
        const dbCount = dbInventory[sku] || 0;
        const shopifyData = shopifyInventory[sku] || { quantity: 0, productTitle: null, variantTitle: null, productNumericId: null };
        const diff = dbCount - shopifyData.quantity;
        const parsedVariant = parseVariantSku(sku);
        inventory.push({
          sku,
          sku_group: parsedVariant.kind ? parsedVariant.group_sku : null,
          totalCount,
          dbCount,
          shopifyCount: shopifyData.quantity,
          diff,
          productTitle: shopifyData.productTitle,
          variantTitle: shopifyData.variantTitle,
          productNumericId: shopifyData.productNumericId,
        });
      }
      inventory.sort((a, b) => a.sku.localeCompare(b.sku));
      return json({ inventory });
    } catch (error) {
      console.error("Error fetching inventory:", error);
      return json({ error: "Failed to fetch inventory", message: error.message }, { status: 500 });
    }
  }

  if (intent === "sync") {
    try {
      const dbResult = await query(
        `SELECT sku_group, length, connector_code, COUNT(*) as count
         FROM audio_cables
         WHERE shopify_gid IS NULL OR shopify_gid = ''
         GROUP BY sku_group, length, connector_code
         ORDER BY sku_group, length, connector_code`
      );
      const dbInventory = {};
      for (const row of dbResult.rows) {
        const variantSku = formatVariantSku({
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

      // Iterate Shopify-side variants we recognise (catalog/MISC/LTD shapes)
      // and reconcile to dbCount, defaulting to 0 for sold-out variants.
      const results = [];
      const skusToSync = Object.keys(variantsBySku).filter(
        (sku) => parseVariantSku(sku).kind !== null
      );

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

export default function Inventory() {
  const submit = useSubmit();
  const actionData = useActionData();
  const { adminPath, appHandle } = useLoaderData();

  // Both held in local state so a Sync followed by an auto-fetch (or vice
  // versa) doesn't blow away the other panel — actionData only ever holds
  // the most recent action's payload.
  const [inventory, setInventory] = useState([]);
  const [syncResults, setSyncResults] = useState(null);
  const [filter, setFilter] = useState("");

  const filterLower = filter.trim().toLowerCase();
  const filteredInventory = filterLower
    ? inventory.filter((item) =>
        item.sku.toLowerCase().includes(filterLower) ||
        (item.productTitle || "").toLowerCase().includes(filterLower) ||
        (item.variantTitle || "").toLowerCase().includes(filterLower)
      )
    : inventory;

  useEffect(() => {
    if (actionData?.inventory) setInventory(actionData.inventory);
  }, [actionData?.inventory]);

  useEffect(() => {
    if (actionData?.syncResults) setSyncResults(actionData.syncResults);
  }, [actionData?.syncResults]);

  // Auto-fetch on mount.
  useEffect(() => {
    const fd = new FormData();
    fd.append("intent", "fetch");
    submit(fd, { method: "post" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // After a sync, re-fetch so the table shows the new Shopify quantities.
  // The sync results banner stays visible (it's in local state) until the
  // user dismisses it or runs another sync.
  useEffect(() => {
    if (!actionData?.syncResults) return;
    const fd = new FormData();
    fd.append("intent", "fetch");
    submit(fd, { method: "post" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actionData?.syncResults]);

  return (
    <div style={{ padding: "0 20px 20px", maxWidth: "1200px", margin: "0 auto", fontFamily: "system-ui, -apple-system, sans-serif" }}>
      <h1 style={{ fontSize: "24px", marginBottom: "20px" }}>Inventory Comparison</h1>

      <div style={{ border: "1px solid #ddd", borderRadius: "8px", padding: "20px", backgroundColor: "#fff" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
          <p style={{ margin: 0, color: "#666" }}>Comparing unassigned cables in database vs Shopify product inventory</p>
          <div style={{ display: "flex", gap: "10px" }}>
            <button
              onClick={() => {
                const fd = new FormData();
                fd.append("intent", "fetch");
                submit(fd, { method: "post" });
              }}
              style={{ padding: "8px 16px", backgroundColor: "#008060", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer", fontSize: "14px" }}
            >
              Refresh
            </button>
            <button
              onClick={() => {
                if (confirm("Sync inventory from database to Shopify? This will update Shopify inventory quantities to match unassigned cable counts.")) {
                  const fd = new FormData();
                  fd.append("intent", "sync");
                  submit(fd, { method: "post" });
                }
              }}
              style={{ padding: "8px 16px", backgroundColor: "#5c6ac4", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer", fontSize: "14px" }}
            >
              Sync to Shopify
            </button>
          </div>
        </div>

        {syncResults && (
          <div style={{ marginBottom: "20px", padding: "15px", backgroundColor: "#f0f9ff", border: "1px solid #b3d9ff", borderRadius: "4px", position: "relative" }}>
            <button
              onClick={() => setSyncResults(null)}
              aria-label="Dismiss"
              style={{
                position: "absolute",
                top: "8px",
                right: "8px",
                background: "none",
                border: "none",
                cursor: "pointer",
                fontSize: "18px",
                color: "#666",
                padding: "4px 8px",
                lineHeight: 1,
              }}
            >
              ×
            </button>
            <div style={{ fontWeight: "bold", marginBottom: "10px" }}>Sync Complete</div>
            <div style={{ display: "flex", gap: "20px", flexWrap: "wrap", fontSize: "14px" }}>
              <span style={{ color: "#008060" }}>Synced: {syncResults.synced}</span>
              <span style={{ color: "#666" }}>Unchanged: {syncResults.unchanged}</span>
              <span style={{ color: "#bf5000" }}>Skipped: {syncResults.skipped}</span>
              {syncResults.errors > 0 && <span style={{ color: "#d72c0d" }}>Errors: {syncResults.errors}</span>}
            </div>
            {syncResults.details?.filter((d) => d.status === "synced").length > 0 && (
              <div style={{ marginTop: "10px", fontSize: "13px", color: "#666" }}>
                <strong>Updated:</strong> {syncResults.details.filter((d) => d.status === "synced").map((d) => `${d.sku} (${d.from} → ${d.to})`).join(", ")}
              </div>
            )}
            {syncResults.details?.filter((d) => d.status === "error").length > 0 && (
              <div style={{ marginTop: "10px", fontSize: "13px", color: "#d72c0d" }}>
                <strong>Errors:</strong> {syncResults.details.filter((d) => d.status === "error").map((d) => `${d.sku}: ${d.error}`).join(", ")}
              </div>
            )}
          </div>
        )}

        {inventory.length === 0 ? (
          <div style={{ padding: "40px", textAlign: "center", color: "#666" }}>Loading inventory data...</div>
        ) : (
          <>
            <div style={{ marginBottom: "12px", display: "flex", gap: "10px", alignItems: "center" }}>
              <input
                type="text"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter by SKU or product…"
                style={{ flex: 1, padding: "8px 10px", border: "1px solid #ccc", borderRadius: "4px", fontSize: "14px" }}
              />
              {filter && (
                <button
                  onClick={() => setFilter("")}
                  style={{ padding: "8px 12px", backgroundColor: "#fff", border: "1px solid #ddd", borderRadius: "4px", fontSize: "14px", cursor: "pointer" }}
                >
                  Clear
                </button>
              )}
              <span style={{ fontSize: "13px", color: "#666", whiteSpace: "nowrap" }}>
                {filterLower
                  ? `${filteredInventory.length} of ${inventory.length}`
                  : `${inventory.length} variants`}
              </span>
            </div>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "14px" }}>
              <thead>
                <tr style={{ backgroundColor: "#f5f5f5" }}>
                  <th style={{ padding: "12px", textAlign: "left", borderBottom: "2px solid #ddd" }}>SKU</th>
                  <th style={{ padding: "12px", textAlign: "left", borderBottom: "2px solid #ddd" }}>Product</th>
                  <th style={{ padding: "12px", textAlign: "right", borderBottom: "2px solid #ddd" }}>Total</th>
                  <th style={{ padding: "12px", textAlign: "right", borderBottom: "2px solid #ddd" }}>Available</th>
                  <th style={{ padding: "12px", textAlign: "right", borderBottom: "2px solid #ddd" }}>Shopify</th>
                  <th style={{ padding: "12px", textAlign: "right", borderBottom: "2px solid #ddd" }}>Difference</th>
                </tr>
              </thead>
              <tbody>
                {filteredInventory.map((item) => {
                  const diffColor = item.diff > 0 ? "#008060" : item.diff < 0 ? "#d72c0d" : "#666";
                  const rowBg = item.diff !== 0 ? "#fffbeb" : "#fff";
                  return (
                    <tr key={item.sku} style={{ backgroundColor: rowBg }}>
                      <td style={{ padding: "12px", borderBottom: "1px solid #eee", fontWeight: "bold" }}>
                        {item.productNumericId ? (
                          <a
                            href={`https://${adminPath}/products/${item.productNumericId}`}
                            target="_top"
                            style={{ color: "#008060", textDecoration: "none" }}
                          >
                            {item.sku}
                          </a>
                        ) : (
                          item.sku
                        )}
                      </td>
                      <td style={{ padding: "12px", borderBottom: "1px solid #eee", color: "#666" }}>
                        {item.productTitle || "—"}
                        {item.variantTitle && item.variantTitle !== "Default Title" && (
                          <span style={{ color: "#999" }}> / {item.variantTitle}</span>
                        )}
                      </td>
                      <td style={{ padding: "12px", borderBottom: "1px solid #eee", textAlign: "right" }}>
                        <a
                          href={item.sku_group ? `https://${adminPath}/apps/${appHandle}/app/cables/${encodeURIComponent(item.sku_group)}` : "#"}
                          target="_top"
                          style={{ color: "#008060", textDecoration: "none", fontWeight: "bold" }}
                        >
                          {item.totalCount}
                        </a>
                      </td>
                      <td style={{ padding: "12px", borderBottom: "1px solid #eee", textAlign: "right" }}>{item.dbCount}</td>
                      <td style={{ padding: "12px", borderBottom: "1px solid #eee", textAlign: "right" }}>{item.shopifyCount}</td>
                      <td style={{ padding: "12px", borderBottom: "1px solid #eee", textAlign: "right", fontWeight: "bold", color: diffColor }}>
                        {item.diff > 0 ? "+" : ""}{item.diff}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {filterLower && filteredInventory.length === 0 && (
              <div style={{ padding: "20px", textAlign: "center", color: "#666", fontSize: "14px" }}>
                No variants match "{filter}".
              </div>
            )}

            <div style={{ marginTop: "20px", padding: "15px", backgroundColor: "#f5f5f5", borderRadius: "4px", fontSize: "13px", color: "#666" }}>
              <strong>Legend:</strong> Total = all cables in DB. Available = unassigned cables. Difference = Available − Shopify.
              <span style={{ color: "#008060", marginLeft: "10px" }}>+Positive</span> means more available than Shopify shows.
              <span style={{ color: "#d72c0d", marginLeft: "10px" }}>−Negative</span> means less available than Shopify shows.
            </div>
          </div>
          </>
        )}
      </div>
    </div>
  );
}
