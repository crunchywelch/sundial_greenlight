import { useState, useEffect } from "react";
import { useSubmit, useActionData, useLoaderData } from "@remix-run/react";
import { json } from "@remix-run/node";
import { authenticate } from "../shopify.server";
import { query } from "../db.server";

export async function loader({ request }) {
  const url = new URL(request.url);
  const host = url.searchParams.get("host") || "";

  // Decode host to get admin path (e.g., "admin.shopify.com/store/sundial-audio-dev")
  let adminPath = "";
  try {
    adminPath = atob(host);
  } catch (e) {
    // If decode fails, leave empty
  }

  // App handle from environment variable
  const appHandle = process.env.SHOPIFY_APP_HANDLE || "greenlight-2";

  return json({ adminPath, appHandle });
}

// Hook to receive scanner events via polling (SSE blocked in Shopify iframe)
function useScannerEvents(enabled) {
  const [lastScanEvent, setLastScanEvent] = useState(null);
  const [lastTimestamp, setLastTimestamp] = useState(0);

  useEffect(() => {
    // Only poll when enabled (on scan/assign views)
    if (!enabled) return;

    // Poll for new scans every 500ms
    const interval = setInterval(async () => {
      try {
        const response = await fetch(`/api/scanner-events?since=${lastTimestamp}`);
        const data = await response.json();

        if (data.serial && data.timestamp > lastTimestamp) {
          console.log("Scanner event received:", data.serial);
          setLastScanEvent({ serial: data.serial, timestamp: data.timestamp });
          setLastTimestamp(data.timestamp);
        }
      } catch (error) {
        // Silently fail, will retry on next interval
      }
    }, 500);

    return () => clearInterval(interval);
  }, [lastTimestamp, enabled]);

  return lastScanEvent;
}

export async function action({ request }) {
  const { admin } = await authenticate.admin(request);
  const formData = await request.formData();
  const action = formData.get("action");

  if (action === "assign") {
    const serialNumber = formData.get("serialNumber");
    const customerId = formData.get("customerId");

    try {
      await query(
        "UPDATE audio_cables SET shopify_gid = $1, updated_timestamp = NOW() WHERE serial_number = $2",
        [customerId, serialNumber]
      );

      return json({ success: true, message: `Cable ${serialNumber} assigned to customer!` });
    } catch (error) {
      console.error("Error assigning cable:", error);
      return json({ success: false, error: "Failed to assign cable" }, { status: 500 });
    }
  }

  if (action === "searchCustomer") {
    const searchTerm = formData.get("searchTerm");
    console.log("Customer search requested for:", searchTerm);
    try {
      const response = await admin.graphql(
        `#graphql
        query searchCustomers($query: String!) {
          customers(first: 10, query: $query) {
            edges {
              node {
                id
                firstName
                lastName
                email
                phone
              }
            }
          }
        }`,
        { variables: { query: searchTerm } }
      );

      const data = await response.json();
      console.log("GraphQL response:", JSON.stringify(data));

      if (data.errors) {
        console.error("GraphQL errors:", data.errors);
        return json({ error: "GraphQL query failed", details: data.errors }, { status: 500 });
      }

      const customers = data.data?.customers?.edges || [];
      console.log(`Found ${customers.length} customers`);
      return json({ customers });
    } catch (error) {
      console.error("Error searching customers:", error);
      return json({ error: "Failed to search customers", message: error.message }, { status: 500 });
    }
  }

  if (action === "searchCable") {
    const searchTerm = formData.get("searchTerm");
    try {
      const result = await query(
        `SELECT ac.serial_number, ac.sku, ac.description, ac.shopify_gid, ac.length as cable_length, cs.series, cs.length as sku_length
         FROM audio_cables ac
         LEFT JOIN cable_skus cs ON ac.sku = cs.sku
         WHERE ac.serial_number ILIKE $1
         ORDER BY ac.serial_number
         LIMIT 20`,
        [`%${searchTerm}%`]
      );

      const cables = result.rows;

      // For cables with shopify_gid, fetch customer details
      for (const cable of cables) {
        if (cable.shopify_gid) {
          try {
            const response = await admin.graphql(
              `#graphql
              query getCustomer($id: ID!) {
                customer(id: $id) {
                  id
                  firstName
                  lastName
                  email
                  phone
                }
              }`,
              { variables: { id: cable.shopify_gid } }
            );

            const data = await response.json();
            if (data.data?.customer) {
              cable.customer = data.data.customer;
            }
          } catch (error) {
            console.error(`Error fetching customer for cable ${cable.serial_number}:`, error);
          }
        }
      }

      return json({ cables });
    } catch (error) {
      console.error("Error searching cables:", error);
      return json({ error: "Failed to search cables" }, { status: 500 });
    }
  }

  if (action === "fetchInventory") {
    try {
      // Get total cable counts from database grouped by SKU (all cables)
      const totalResult = await query(
        `SELECT sku, COUNT(*) as count
         FROM audio_cables
         GROUP BY sku
         ORDER BY sku`
      );
      const totalInventory = {};
      for (const row of totalResult.rows) {
        totalInventory[row.sku] = parseInt(row.count);
      }

      // Get available cable counts from database grouped by SKU (only unassigned cables)
      const dbResult = await query(
        `SELECT sku, COUNT(*) as count
         FROM audio_cables
         WHERE shopify_gid IS NULL OR shopify_gid = ''
         GROUP BY sku
         ORDER BY sku`
      );
      const dbInventory = {};
      for (const row of dbResult.rows) {
        dbInventory[row.sku] = parseInt(row.count);
      }

      // Fetch products from Shopify with their inventory
      const shopifyInventory = {};
      let hasNextPage = true;
      let cursor = null;

      while (hasNextPage) {
        const response = await admin.graphql(
          `#graphql
          query getProducts($cursor: String) {
            products(first: 50, after: $cursor) {
              pageInfo {
                hasNextPage
                endCursor
              }
              edges {
                node {
                  id
                  title
                  variants(first: 100) {
                    edges {
                      node {
                        id
                        sku
                        inventoryQuantity
                        title
                      }
                    }
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
          for (const variantEdge of product.variants.edges) {
            const variant = variantEdge.node;
            if (variant.sku) {
              shopifyInventory[variant.sku] = {
                quantity: variant.inventoryQuantity,
                productTitle: product.title,
                variantTitle: variant.title
              };
            }
          }
        }

        hasNextPage = products.pageInfo.hasNextPage;
        cursor = products.pageInfo.endCursor;
      }

      // Combine into comparison data
      const allSkus = new Set([...Object.keys(totalInventory), ...Object.keys(dbInventory), ...Object.keys(shopifyInventory)]);
      const inventory = [];

      for (const sku of allSkus) {
        const totalCount = totalInventory[sku] || 0;
        const dbCount = dbInventory[sku] || 0;
        const shopifyData = shopifyInventory[sku] || { quantity: 0, productTitle: null, variantTitle: null };
        const diff = dbCount - shopifyData.quantity;

        inventory.push({
          sku,
          totalCount,
          dbCount,
          shopifyCount: shopifyData.quantity,
          diff,
          productTitle: shopifyData.productTitle,
          variantTitle: shopifyData.variantTitle
        });
      }

      // Sort by SKU
      inventory.sort((a, b) => a.sku.localeCompare(b.sku));

      return json({ inventory });
    } catch (error) {
      console.error("Error fetching inventory:", error);
      return json({ error: "Failed to fetch inventory", message: error.message }, { status: 500 });
    }
  }

  if (action === "syncInventory") {
    try {
      // Get cable counts from database grouped by SKU (only unassigned cables = available inventory)
      const dbResult = await query(
        `SELECT sku, COUNT(*) as count
         FROM audio_cables
         WHERE shopify_gid IS NULL OR shopify_gid = ''
         GROUP BY sku
         ORDER BY sku`
      );
      const dbInventory = {};
      for (const row of dbResult.rows) {
        dbInventory[row.sku] = parseInt(row.count);
      }

      // Get the primary location ID
      const locationResponse = await admin.graphql(
        `#graphql
        query getLocations {
          locations(first: 1) {
            edges {
              node {
                id
              }
            }
          }
        }`
      );
      const locationData = await locationResponse.json();
      console.log("Location response:", JSON.stringify(locationData, null, 2));

      if (locationData.errors) {
        console.error("Location GraphQL errors:", JSON.stringify(locationData.errors, null, 2));
        return json({ error: "GraphQL error fetching location", details: locationData.errors }, { status: 500 });
      }

      const locationId = locationData.data?.locations?.edges?.[0]?.node?.id;

      if (!locationId) {
        return json({ error: "Could not find location" }, { status: 500 });
      }

      // Get all product variants with their inventory item IDs
      const variantsBySku = {};
      let hasNextPage = true;
      let cursor = null;

      while (hasNextPage) {
        const response = await admin.graphql(
          `#graphql
          query getProductVariants($cursor: String) {
            productVariants(first: 100, after: $cursor) {
              pageInfo {
                hasNextPage
                endCursor
              }
              edges {
                node {
                  id
                  sku
                  inventoryItem {
                    id
                  }
                  inventoryQuantity
                }
              }
            }
          }`,
          { variables: { cursor } }
        );

        const data = await response.json();
        if (data.errors) {
          console.error("Variants GraphQL errors:", JSON.stringify(data.errors, null, 2));
          break;
        }

        const variants = data.data?.productVariants;
        if (!variants) break;

        for (const edge of variants.edges) {
          const variant = edge.node;
          if (variant.sku && variant.inventoryItem?.id) {
            variantsBySku[variant.sku] = {
              variantId: variant.id,
              inventoryItemId: variant.inventoryItem.id,
              currentQuantity: variant.inventoryQuantity
            };
          }
        }

        hasNextPage = variants.pageInfo.hasNextPage;
        cursor = variants.pageInfo.endCursor;
      }

      // Sync inventory for each SKU
      const results = [];
      const skusToSync = Object.keys(dbInventory);

      for (const sku of skusToSync) {
        const dbCount = dbInventory[sku];
        const variantInfo = variantsBySku[sku];

        if (!variantInfo) {
          results.push({ sku, status: "skipped", reason: "No Shopify variant found" });
          continue;
        }

        if (variantInfo.currentQuantity === dbCount) {
          results.push({ sku, status: "unchanged", quantity: dbCount });
          continue;
        }

        // Set the inventory quantity
        try {
          const setResponse = await admin.graphql(
            `#graphql
            mutation inventorySetQuantities($input: InventorySetQuantitiesInput!) {
              inventorySetQuantities(input: $input) {
                inventoryAdjustmentGroup {
                  reason
                }
                userErrors {
                  field
                  message
                }
              }
            }`,
            {
              variables: {
                input: {
                  name: "available",
                  reason: "correction",
                  ignoreCompareQuantity: true,
                  quantities: [
                    {
                      inventoryItemId: variantInfo.inventoryItemId,
                      locationId: locationId,
                      quantity: dbCount
                    }
                  ]
                }
              }
            }
          );

          const setData = await setResponse.json();
          if (setData.data?.inventorySetQuantities?.userErrors?.length > 0) {
            results.push({
              sku,
              status: "error",
              error: setData.data.inventorySetQuantities.userErrors[0].message
            });
          } else {
            results.push({
              sku,
              status: "synced",
              from: variantInfo.currentQuantity,
              to: dbCount
            });
          }
        } catch (err) {
          results.push({ sku, status: "error", error: err.message });
        }
      }

      const synced = results.filter(r => r.status === "synced").length;
      const unchanged = results.filter(r => r.status === "unchanged").length;
      const skipped = results.filter(r => r.status === "skipped").length;
      const errors = results.filter(r => r.status === "error").length;

      return json({
        syncResults: {
          synced,
          unchanged,
          skipped,
          errors,
          details: results
        }
      });
    } catch (error) {
      console.error("Error syncing inventory:", error);
      console.error("Error stack:", error.stack);
      if (error.graphQLErrors) {
        console.error("GraphQL errors:", JSON.stringify(error.graphQLErrors, null, 2));
      }
      return json({ error: "Failed to sync inventory", message: error.message }, { status: 500 });
    }
  }

  return json({ error: "Invalid action" }, { status: 400 });
}

export default function Index() {
  const submit = useSubmit();
  const actionData = useActionData();
  const { adminPath, appHandle } = useLoaderData();

  const [view, setView] = useState("scan"); // "scan", "assign", "customers", or "inventory"
  const [customerLookupSearch, setCustomerLookupSearch] = useState("");
  const [customerSearch, setCustomerSearch] = useState("");
  const [cableSearch, setCableSearch] = useState("");
  const [selectedCustomer, setSelectedCustomer] = useState(null);
  const [selectedCable, setSelectedCable] = useState(null);
  const [scannerActive, setScannerActive] = useState(false);
  const [cableInputFocused, setCableInputFocused] = useState(false);

  const customers = actionData?.customers || [];
  const cables = actionData?.cables || [];
  const inventory = actionData?.inventory || [];
  const syncResults = actionData?.syncResults || null;

  // Listen for scanner events (only when cable search input is focused)
  const scannerEnabled = (view === "scan" || view === "assign") && cableInputFocused;
  const scanEvent = useScannerEvents(scannerEnabled);

  // Auto-fill and search when scanner sends a serial number
  useEffect(() => {
    if (scanEvent?.serial) {
      console.log("Auto-filling cable search with scanned serial:", scanEvent.serial);
      setCableSearch(scanEvent.serial);

      // Show scanner indicator
      setScannerActive(true);
      setTimeout(() => setScannerActive(false), 2000);

      // Automatically trigger cable search
      const formData = new FormData();
      formData.append("action", "searchCable");
      formData.append("searchTerm", scanEvent.serial);
      submit(formData, { method: "post" });
    }
  }, [scanEvent?.timestamp, submit]);

  const handleCustomerSearch = (e) => {
    e.preventDefault();
    const formData = new FormData();
    formData.append("action", "searchCustomer");
    formData.append("searchTerm", customerSearch);
    submit(formData, { method: "post" });
  };

  const handleCableSearch = (e) => {
    e.preventDefault();
    const formData = new FormData();
    formData.append("action", "searchCable");
    formData.append("searchTerm", cableSearch);
    submit(formData, { method: "post" });
  };

  const handleAssign = () => {
    if (!selectedCustomer || !selectedCable) return;
    const formData = new FormData();
    formData.append("action", "assign");
    formData.append("customerId", selectedCustomer.id);
    formData.append("serialNumber", selectedCable.serial_number);
    submit(formData, { method: "post" });
  };

  return (
    <>
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>
      <div style={{ padding: '20px', maxWidth: '1200px', margin: '0 auto', fontFamily: 'system-ui, -apple-system, sans-serif' }}>
        {/* Menu */}
        <div style={{ display: 'flex', gap: '10px', marginBottom: '20px', borderBottom: '2px solid #ddd', paddingBottom: '10px' }}>
          <button
            onClick={() => setView("scan")}
            style={{
              padding: '10px 20px',
              backgroundColor: view === "scan" ? '#008060' : '#fff',
              color: view === "scan" ? '#fff' : '#333',
              border: view === "scan" ? 'none' : '1px solid #ddd',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '16px',
              fontWeight: view === "scan" ? 'bold' : 'normal'
            }}
          >
            Scan Cable
          </button>
          <button
            onClick={() => setView("assign")}
            style={{
              padding: '10px 20px',
              backgroundColor: view === "assign" ? '#008060' : '#fff',
              color: view === "assign" ? '#fff' : '#333',
              border: view === "assign" ? 'none' : '1px solid #ddd',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '16px',
              fontWeight: view === "assign" ? 'bold' : 'normal'
            }}
          >
            Assign Cable
          </button>
          <button
            onClick={() => setView("customers")}
            style={{
              padding: '10px 20px',
              backgroundColor: view === "customers" ? '#008060' : '#fff',
              color: view === "customers" ? '#fff' : '#333',
              border: view === "customers" ? 'none' : '1px solid #ddd',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '16px',
              fontWeight: view === "customers" ? 'bold' : 'normal'
            }}
          >
            Customer Lookup
          </button>
          <button
            onClick={() => {
              setView("inventory");
              // Trigger inventory fetch when switching to this view
              const formData = new FormData();
              formData.append("action", "fetchInventory");
              submit(formData, { method: "post" });
            }}
            style={{
              padding: '10px 20px',
              backgroundColor: view === "inventory" ? '#008060' : '#fff',
              color: view === "inventory" ? '#fff' : '#333',
              border: view === "inventory" ? 'none' : '1px solid #ddd',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '16px',
              fontWeight: view === "inventory" ? 'bold' : 'normal'
            }}
          >
            Inventory
          </button>
        </div>

        {/* Scan Cable View - Info Only */}
        {view === "scan" && (
          <div>
            <h1 style={{ fontSize: '24px', marginBottom: '20px' }}>Scan Cable</h1>

            <div style={{ border: '1px solid #ddd', borderRadius: '8px', padding: '20px', backgroundColor: '#fff', marginBottom: '20px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px' }}>
                <h2 style={{ fontSize: '18px', margin: 0 }}>Cable Lookup</h2>
                {scannerActive && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#008060', fontSize: '14px', fontWeight: 'bold' }}>
                    <div style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: '#008060', animation: 'pulse 1s infinite' }}></div>
                    Scanner Active
                  </div>
                )}
              </div>

              <form onSubmit={handleCableSearch} style={{ marginBottom: '20px' }}>
                <label style={{ display: 'block', marginBottom: '5px', fontSize: '14px' }}>
                  Search by serial number
                </label>
                <div style={{ display: 'flex', gap: '10px' }}>
                  <input
                    type="text"
                    value={cableSearch}
                    onChange={(e) => setCableSearch(e.target.value)}
                    onFocus={() => setCableInputFocused(true)}
                    onBlur={() => setCableInputFocused(false)}
                    style={{
                      flex: 1,
                      padding: '10px',
                      border: scannerActive ? '2px solid #008060' : '1px solid #ccc',
                      borderRadius: '4px',
                      fontSize: '16px',
                      backgroundColor: scannerActive ? '#f0f9ff' : '#fff'
                    }}
                  />
                  <button type="submit" style={{ padding: '10px 20px', backgroundColor: '#008060', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '16px' }}>
                    Search
                  </button>
                </div>
              </form>

              {cables.length > 0 && (
                <div>
                  <h3 style={{ fontSize: '16px', marginBottom: '10px' }}>Results:</h3>
                  {cables.map((item) => {
                    // For MISC cables, use cable_length; otherwise use sku_length
                    const displayLength = item.sku?.endsWith('MISC') ? item.cable_length : item.sku_length;

                    return (
                      <div
                        key={item.serial_number}
                        style={{
                          padding: '15px',
                          border: '1px solid #ddd',
                          borderRadius: '4px',
                          marginBottom: '10px',
                          backgroundColor: '#fff'
                        }}
                      >
                        <div style={{ fontWeight: 'bold', fontSize: '18px', marginBottom: '8px' }}>
                          {item.serial_number}
                        </div>
                        <div style={{ fontSize: '14px', color: '#666', marginBottom: '4px' }}>SKU: {item.sku}</div>
                        {item.series && <div style={{ fontSize: '14px', color: '#666', marginBottom: '4px' }}>Series: {item.series}</div>}
                        {displayLength && <div style={{ fontSize: '14px', color: '#666', marginBottom: '4px' }}>Length: {displayLength}</div>}
                        {item.description && <div style={{ fontSize: '14px', color: '#666', marginBottom: '4px' }}>{item.description}</div>}

                        {item.customer ? (
                          <div style={{ marginTop: '12px', padding: '10px', backgroundColor: '#f0f9ff', border: '1px solid #b3d9ff', borderRadius: '4px' }}>
                            <div style={{ fontSize: '14px', color: '#008060', fontWeight: 'bold', marginBottom: '6px' }}>✓ Assigned to:</div>
                            <div style={{ fontSize: '14px', color: '#333', fontWeight: 'bold' }}>{item.customer.firstName} {item.customer.lastName}</div>
                            {item.customer.email && <div style={{ fontSize: '13px', color: '#666' }}>{item.customer.email}</div>}
                            {item.customer.phone && <div style={{ fontSize: '13px', color: '#666' }}>{item.customer.phone}</div>}
                          </div>
                        ) : item.shopify_gid ? (
                          <div style={{ fontSize: '14px', color: '#008060', marginTop: '8px', fontWeight: 'bold' }}>✓ Assigned to customer</div>
                        ) : (
                          <div style={{ fontSize: '14px', color: '#999', marginTop: '8px' }}>Not yet assigned</div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Assign Cable View - Full Interface */}
        {view === "assign" && (
          <div>
            <h1 style={{ fontSize: '24px', marginBottom: '20px' }}>Assign Cable to Customer</h1>

            {actionData?.success && (
              <div style={{ padding: '15px', backgroundColor: '#d4edda', border: '1px solid #c3e6cb', borderRadius: '4px', marginBottom: '20px', color: '#155724' }}>
                {actionData.message}
              </div>
            )}

            {actionData?.error && (
              <div style={{ padding: '15px', backgroundColor: '#f8d7da', border: '1px solid #f5c6cb', borderRadius: '4px', marginBottom: '20px', color: '#721c24' }}>
                {actionData.error}
              </div>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginBottom: '20px' }}>
              <div style={{ border: '1px solid #ddd', borderRadius: '8px', padding: '20px', backgroundColor: '#fff' }}>
                <h2 style={{ fontSize: '18px', marginBottom: '15px' }}>Select Customer</h2>

                <form onSubmit={handleCustomerSearch} style={{ marginBottom: '15px' }}>
                  <label style={{ display: 'block', marginBottom: '5px', fontSize: '14px' }}>
                    Search by name, email, or phone
                  </label>
                  <div style={{ display: 'flex', gap: '10px' }}>
                    <input
                      type="text"
                      value={customerSearch}
                      onChange={(e) => setCustomerSearch(e.target.value)}
                      style={{ flex: 1, padding: '8px', border: '1px solid #ccc', borderRadius: '4px', fontSize: '14px' }}
                    />
                    <button type="submit" style={{ padding: '8px 16px', backgroundColor: '#008060', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '14px' }}>
                      Search
                    </button>
                  </div>
                </form>

                {selectedCustomer && (
                  <div style={{ padding: '10px', backgroundColor: '#e8f5ff', border: '1px solid #b3d9ff', borderRadius: '4px', marginBottom: '15px', fontSize: '14px' }}>
                    Selected: {selectedCustomer.firstName} {selectedCustomer.lastName} ({selectedCustomer.email})
                  </div>
                )}

                {customers.length > 0 && (
                  <div>
                    {customers.map((item) => {
                      const { node } = item;
                      return (
                        <div
                          key={node.id}
                          onClick={() => setSelectedCustomer(node)}
                          style={{
                            padding: '12px',
                            border: '1px solid #ddd',
                            borderRadius: '4px',
                            marginBottom: '8px',
                            cursor: 'pointer',
                            backgroundColor: selectedCustomer?.id === node.id ? '#f0f9ff' : '#fff'
                          }}
                        >
                          <div style={{ fontWeight: 'bold', marginBottom: '4px' }}>
                            {node.firstName} {node.lastName}
                          </div>
                          <div style={{ fontSize: '13px', color: '#666' }}>{node.email}</div>
                          {node.phone && <div style={{ fontSize: '13px', color: '#666' }}>{node.phone}</div>}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              <div style={{ border: '1px solid #ddd', borderRadius: '8px', padding: '20px', backgroundColor: '#fff' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px' }}>
                  <h2 style={{ fontSize: '18px', margin: 0 }}>Select Cable</h2>
                  {scannerActive && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#008060', fontSize: '14px', fontWeight: 'bold' }}>
                      <div style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: '#008060', animation: 'pulse 1s infinite' }}></div>
                      Scanner Active
                    </div>
                  )}
                </div>

                <form onSubmit={handleCableSearch} style={{ marginBottom: '15px' }}>
                  <label style={{ display: 'block', marginBottom: '5px', fontSize: '14px' }}>
                    Search by serial number
                  </label>
                  <div style={{ display: 'flex', gap: '10px' }}>
                    <input
                      type="text"
                      value={cableSearch}
                      onChange={(e) => setCableSearch(e.target.value)}
                      onFocus={() => setCableInputFocused(true)}
                      onBlur={() => setCableInputFocused(false)}
                      style={{
                        flex: 1,
                        padding: '8px',
                        border: scannerActive ? '2px solid #008060' : '1px solid #ccc',
                        borderRadius: '4px',
                        fontSize: '14px',
                        backgroundColor: scannerActive ? '#f0f9ff' : '#fff'
                      }}
                    />
                    <button type="submit" style={{ padding: '8px 16px', backgroundColor: '#008060', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '14px' }}>
                      Search
                    </button>
                  </div>
                </form>

                {selectedCable && (
                  <div style={{ padding: '10px', backgroundColor: '#e8f5ff', border: '1px solid #b3d9ff', borderRadius: '4px', marginBottom: '15px', fontSize: '14px' }}>
                    Selected: {selectedCable.serial_number} ({selectedCable.sku})
                    {selectedCable.customer && (
                      <div style={{ color: '#ff8c00', marginTop: '4px' }}>
                        ⚠️ Already assigned to {selectedCable.customer.firstName} {selectedCable.customer.lastName}
                      </div>
                    )}
                  </div>
                )}

                {cables.length > 0 && (
                  <div>
                    {cables.map((item) => (
                      <div
                        key={item.serial_number}
                        onClick={() => setSelectedCable(item)}
                        style={{
                          padding: '12px',
                          border: '1px solid #ddd',
                          borderRadius: '4px',
                          marginBottom: '8px',
                          cursor: 'pointer',
                          backgroundColor: selectedCable?.serial_number === item.serial_number ? '#f0f9ff' : '#fff'
                        }}
                      >
                        <div style={{ fontWeight: 'bold', marginBottom: '4px' }}>
                          {item.serial_number}
                        </div>
                        <div style={{ fontSize: '13px', color: '#666' }}>SKU: {item.sku}</div>
                        {item.series && <div style={{ fontSize: '13px', color: '#666' }}>Series: {item.series}</div>}
                        {item.description && <div style={{ fontSize: '13px', color: '#666' }}>{item.description}</div>}
                        {item.customer && (
                          <div style={{ fontSize: '13px', color: '#ff8c00', marginTop: '4px' }}>
                            ⚠️ Already assigned to {item.customer.firstName} {item.customer.lastName}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div style={{ border: '1px solid #ddd', borderRadius: '8px', padding: '20px', backgroundColor: '#fff', textAlign: 'center' }}>
              <button
                onClick={handleAssign}
                disabled={!selectedCustomer || !selectedCable}
                style={{
                  padding: '12px 24px',
                  backgroundColor: (!selectedCustomer || !selectedCable) ? '#ccc' : '#008060',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '4px',
                  cursor: (!selectedCustomer || !selectedCable) ? 'not-allowed' : 'pointer',
                  fontSize: '16px',
                  fontWeight: 'bold'
                }}
              >
                Assign Cable to Customer
              </button>
            </div>
          </div>
        )}

        {/* Customer Lookup View */}
        {view === "customers" && (
          <div>
            <h1 style={{ fontSize: '24px', marginBottom: '20px' }}>Customer Lookup</h1>

            <div style={{ border: '1px solid #ddd', borderRadius: '8px', padding: '20px', backgroundColor: '#fff' }}>
              <form onSubmit={(e) => {
                e.preventDefault();
                const formData = new FormData();
                formData.append("action", "searchCustomer");
                formData.append("searchTerm", customerLookupSearch);
                submit(formData, { method: "post" });
              }} style={{ marginBottom: '20px' }}>
                <label style={{ display: 'block', marginBottom: '5px', fontSize: '14px' }}>
                  Search by name, email, or phone
                </label>
                <div style={{ display: 'flex', gap: '10px' }}>
                  <input
                    type="text"
                    value={customerLookupSearch}
                    onChange={(e) => setCustomerLookupSearch(e.target.value)}
                    placeholder="Enter customer name, email, or phone..."
                    style={{
                      flex: 1,
                      padding: '10px',
                      border: '1px solid #ccc',
                      borderRadius: '4px',
                      fontSize: '16px'
                    }}
                  />
                  <button type="submit" style={{ padding: '10px 20px', backgroundColor: '#008060', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '16px' }}>
                    Search
                  </button>
                </div>
              </form>

              {customers.length > 0 && (
                <div>
                  <h3 style={{ fontSize: '16px', marginBottom: '10px' }}>Results ({customers.length}):</h3>
                  {customers.map((item) => {
                    const { node } = item;
                    const numericId = node.id?.split("/").pop();
                    return (
                      <a
                        key={node.id}
                        href={`https://${adminPath}/apps/${appHandle}/app/customer/${numericId}/cables`}
                        target="_top"
                        style={{
                          display: 'block',
                          padding: '15px',
                          border: '1px solid #ddd',
                          borderRadius: '4px',
                          marginBottom: '10px',
                          cursor: 'pointer',
                          backgroundColor: '#fff',
                          textDecoration: 'none',
                          color: 'inherit'
                        }}
                      >
                        <div style={{ fontWeight: 'bold', fontSize: '16px', marginBottom: '4px' }}>
                          {node.firstName} {node.lastName}
                        </div>
                        <div style={{ fontSize: '14px', color: '#666' }}>{node.email}</div>
                        {node.phone && <div style={{ fontSize: '14px', color: '#666' }}>{node.phone}</div>}
                        <div style={{ fontSize: '13px', color: '#008060', marginTop: '8px' }}>
                          Click to view cables →
                        </div>
                      </a>
                    );
                  })}
                </div>
              )}

              {customers.length === 0 && customerLookupSearch && !actionData?.error && (
                <div style={{ padding: '20px', textAlign: 'center', color: '#666' }}>
                  No customers found. Try a different search term.
                </div>
              )}
            </div>
          </div>
        )}

        {/* Inventory View */}
        {view === "inventory" && (
          <div>
            <h1 style={{ fontSize: '24px', marginBottom: '20px' }}>Inventory Comparison</h1>

            <div style={{ border: '1px solid #ddd', borderRadius: '8px', padding: '20px', backgroundColor: '#fff' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                <p style={{ margin: 0, color: '#666' }}>
                  Comparing unassigned cables in database vs Shopify product inventory
                </p>
                <div style={{ display: 'flex', gap: '10px' }}>
                  <button
                    onClick={() => {
                      const formData = new FormData();
                      formData.append("action", "fetchInventory");
                      submit(formData, { method: "post" });
                    }}
                    style={{ padding: '8px 16px', backgroundColor: '#008060', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '14px' }}
                  >
                    Refresh
                  </button>
                  <button
                    onClick={() => {
                      if (confirm('Sync inventory from database to Shopify? This will update Shopify inventory quantities to match unassigned cable counts.')) {
                        const formData = new FormData();
                        formData.append("action", "syncInventory");
                        submit(formData, { method: "post" });
                      }
                    }}
                    style={{ padding: '8px 16px', backgroundColor: '#5c6ac4', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '14px' }}
                  >
                    Sync to Shopify
                  </button>
                </div>
              </div>

              {syncResults && (
                <div style={{ marginBottom: '20px', padding: '15px', backgroundColor: '#f0f9ff', border: '1px solid #b3d9ff', borderRadius: '4px' }}>
                  <div style={{ fontWeight: 'bold', marginBottom: '10px' }}>Sync Complete</div>
                  <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap', fontSize: '14px' }}>
                    <span style={{ color: '#008060' }}>Synced: {syncResults.synced}</span>
                    <span style={{ color: '#666' }}>Unchanged: {syncResults.unchanged}</span>
                    <span style={{ color: '#bf5000' }}>Skipped: {syncResults.skipped}</span>
                    {syncResults.errors > 0 && <span style={{ color: '#d72c0d' }}>Errors: {syncResults.errors}</span>}
                  </div>
                  {syncResults.details?.filter(d => d.status === 'synced').length > 0 && (
                    <div style={{ marginTop: '10px', fontSize: '13px', color: '#666' }}>
                      <strong>Updated:</strong> {syncResults.details.filter(d => d.status === 'synced').map(d => `${d.sku} (${d.from} → ${d.to})`).join(', ')}
                    </div>
                  )}
                  {syncResults.details?.filter(d => d.status === 'skipped').length > 0 && (
                    <div style={{ marginTop: '10px', fontSize: '13px', color: '#bf5000' }}>
                      <strong>Skipped (no Shopify variant):</strong> {syncResults.details.filter(d => d.status === 'skipped').map(d => d.sku).join(', ')}
                    </div>
                  )}
                  {syncResults.details?.filter(d => d.status === 'error').length > 0 && (
                    <div style={{ marginTop: '10px', fontSize: '13px', color: '#d72c0d' }}>
                      <strong>Errors:</strong> {syncResults.details.filter(d => d.status === 'error').map(d => `${d.sku}: ${d.error}`).join(', ')}
                    </div>
                  )}
                </div>
              )}

              {inventory.length === 0 ? (
                <div style={{ padding: '40px', textAlign: 'center', color: '#666' }}>
                  Loading inventory data...
                </div>
              ) : (
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '14px' }}>
                    <thead>
                      <tr style={{ backgroundColor: '#f5f5f5' }}>
                        <th style={{ padding: '12px', textAlign: 'left', borderBottom: '2px solid #ddd' }}>SKU</th>
                        <th style={{ padding: '12px', textAlign: 'left', borderBottom: '2px solid #ddd' }}>Product</th>
                        <th style={{ padding: '12px', textAlign: 'right', borderBottom: '2px solid #ddd' }}>Total</th>
                        <th style={{ padding: '12px', textAlign: 'right', borderBottom: '2px solid #ddd' }}>Available</th>
                        <th style={{ padding: '12px', textAlign: 'right', borderBottom: '2px solid #ddd' }}>Shopify</th>
                        <th style={{ padding: '12px', textAlign: 'right', borderBottom: '2px solid #ddd' }}>Difference</th>
                      </tr>
                    </thead>
                    <tbody>
                      {inventory.map((item) => {
                        const diffColor = item.diff > 0 ? '#008060' : item.diff < 0 ? '#d72c0d' : '#666';
                        const rowBg = item.diff !== 0 ? '#fffbeb' : '#fff';
                        return (
                          <tr key={item.sku} style={{ backgroundColor: rowBg }}>
                            <td style={{ padding: '12px', borderBottom: '1px solid #eee', fontWeight: 'bold' }}>
                              {item.sku}
                            </td>
                            <td style={{ padding: '12px', borderBottom: '1px solid #eee', color: '#666' }}>
                              {item.productTitle || '—'}
                              {item.variantTitle && item.variantTitle !== 'Default Title' && (
                                <span style={{ color: '#999' }}> / {item.variantTitle}</span>
                              )}
                            </td>
                            <td style={{ padding: '12px', borderBottom: '1px solid #eee', textAlign: 'right' }}>
                              <a
                                href={`https://${adminPath}/apps/${appHandle}/app/cables/${encodeURIComponent(item.sku)}`}
                                target="_top"
                                style={{ color: '#008060', textDecoration: 'none', fontWeight: 'bold' }}
                              >
                                {item.totalCount}
                              </a>
                            </td>
                            <td style={{ padding: '12px', borderBottom: '1px solid #eee', textAlign: 'right' }}>
                              {item.dbCount}
                            </td>
                            <td style={{ padding: '12px', borderBottom: '1px solid #eee', textAlign: 'right' }}>
                              {item.shopifyCount}
                            </td>
                            <td style={{ padding: '12px', borderBottom: '1px solid #eee', textAlign: 'right', fontWeight: 'bold', color: diffColor }}>
                              {item.diff > 0 ? '+' : ''}{item.diff}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>

                  <div style={{ marginTop: '20px', padding: '15px', backgroundColor: '#f5f5f5', borderRadius: '4px', fontSize: '13px', color: '#666' }}>
                    <strong>Legend:</strong> Total = all cables in DB. Available = unassigned cables. Difference = Available - Shopify.
                    <span style={{ color: '#008060', marginLeft: '10px' }}>+Positive</span> means more available than Shopify shows.
                    <span style={{ color: '#d72c0d', marginLeft: '10px' }}>-Negative</span> means less available than Shopify shows.
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
