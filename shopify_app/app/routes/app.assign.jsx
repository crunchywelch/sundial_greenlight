import { useEffect, useState } from "react";
import { json } from "@remix-run/node";
import { useActionData, useSubmit } from "@remix-run/react";
import { authenticate } from "../shopify.server";
import { query } from "../db.server";
import { seriesForPrefix, formatVariantSku } from "../cable-config.server";
import { useScannerEvents } from "../use-scanner-events";

export async function loader({ request }) {
  await authenticate.admin(request);
  return json({});
}

export async function action({ request }) {
  const { admin } = await authenticate.admin(request);
  const formData = await request.formData();
  const intent = formData.get("intent");

  if (intent === "assign") {
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

  if (intent === "searchCustomer") {
    const searchTerm = formData.get("searchTerm");
    try {
      const response = await admin.graphql(
        `#graphql
        query searchCustomers($query: String!) {
          customers(first: 10, query: $query) {
            edges { node { id firstName lastName email phone } }
          }
        }`,
        { variables: { query: searchTerm } }
      );
      const data = await response.json();
      if (data.errors) {
        return json({ error: "GraphQL query failed", details: data.errors }, { status: 500 });
      }
      return json({ customers: data.data?.customers?.edges || [] });
    } catch (error) {
      return json({ error: "Failed to search customers", message: error.message }, { status: 500 });
    }
  }

  if (intent === "searchCable") {
    const searchTerm = formData.get("searchTerm");
    try {
      const result = await query(
        `SELECT ac.serial_number, ac.sku_group, ac.prefix, ac.length, ac.connector_code, ac.shopify_gid
         FROM audio_cables ac
         WHERE ac.serial_number ILIKE $1
         ORDER BY ac.serial_number
         LIMIT 20`,
        [`%${searchTerm}%`]
      );

      const cables = result.rows.map((row) => ({
        serial_number: row.serial_number,
        shopify_gid: row.shopify_gid,
        sku: formatVariantSku({
          prefix: row.prefix,
          group_sku: row.sku_group,
          length: Number(row.length),
          connector_code: row.connector_code,
        }),
        sku_group: row.sku_group,
        prefix: row.prefix,
        series: seriesForPrefix(row.prefix),
        sku_length: Number(row.length),
      }));

      for (const cable of cables) {
        if (cable.shopify_gid) {
          try {
            const response = await admin.graphql(
              `#graphql
              query getCustomer($id: ID!) {
                customer(id: $id) { id firstName lastName email phone }
              }`,
              { variables: { id: cable.shopify_gid } }
            );
            const data = await response.json();
            if (data.data?.customer) cable.customer = data.data.customer;
          } catch (error) {
            console.error(`Error fetching customer for cable ${cable.serial_number}:`, error);
          }
        }
      }

      return json({ cables });
    } catch (error) {
      return json({ error: "Failed to search cables" }, { status: 500 });
    }
  }

  return json({ error: "Invalid intent" }, { status: 400 });
}

export default function AssignCable() {
  const submit = useSubmit();
  const actionData = useActionData();

  const [customerSearch, setCustomerSearch] = useState("");
  const [cableSearch, setCableSearch] = useState("");
  const [selectedCustomer, setSelectedCustomer] = useState(null);
  const [selectedCable, setSelectedCable] = useState(null);
  const [scannerActive, setScannerActive] = useState(false);
  const [cableInputFocused, setCableInputFocused] = useState(false);

  const customers = actionData?.customers || [];
  const cables = actionData?.cables || [];

  const scanEvent = useScannerEvents(cableInputFocused);

  useEffect(() => {
    if (scanEvent?.serial) {
      setCableSearch(scanEvent.serial);
      setScannerActive(true);
      setTimeout(() => setScannerActive(false), 2000);
      const formData = new FormData();
      formData.append("intent", "searchCable");
      formData.append("searchTerm", scanEvent.serial);
      submit(formData, { method: "post" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scanEvent?.timestamp]);

  const handleCustomerSearch = (e) => {
    e.preventDefault();
    const formData = new FormData();
    formData.append("intent", "searchCustomer");
    formData.append("searchTerm", customerSearch);
    submit(formData, { method: "post" });
  };

  const handleCableSearch = (e) => {
    e.preventDefault();
    const formData = new FormData();
    formData.append("intent", "searchCable");
    formData.append("searchTerm", cableSearch);
    submit(formData, { method: "post" });
  };

  const handleAssign = () => {
    if (!selectedCustomer || !selectedCable) return;
    const formData = new FormData();
    formData.append("intent", "assign");
    formData.append("customerId", selectedCustomer.id);
    formData.append("serialNumber", selectedCable.serial_number);
    submit(formData, { method: "post" });
  };

  return (
    <div style={{ padding: "0 20px 20px", maxWidth: "1200px", margin: "0 auto", fontFamily: "system-ui, -apple-system, sans-serif" }}>
      <h1 style={{ fontSize: "24px", marginBottom: "20px" }}>Assign Cable to Customer</h1>

      {actionData?.success && (
        <div style={{ padding: "15px", backgroundColor: "#d4edda", border: "1px solid #c3e6cb", borderRadius: "4px", marginBottom: "20px", color: "#155724" }}>
          {actionData.message}
        </div>
      )}
      {actionData?.error && (
        <div style={{ padding: "15px", backgroundColor: "#f8d7da", border: "1px solid #f5c6cb", borderRadius: "4px", marginBottom: "20px", color: "#721c24" }}>
          {actionData.error}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px", marginBottom: "20px" }}>
        <div style={{ border: "1px solid #ddd", borderRadius: "8px", padding: "20px", backgroundColor: "#fff" }}>
          <h2 style={{ fontSize: "18px", marginBottom: "15px" }}>Select Customer</h2>

          <form onSubmit={handleCustomerSearch} style={{ marginBottom: "15px" }}>
            <label style={{ display: "block", marginBottom: "5px", fontSize: "14px" }}>Search by name, email, or phone</label>
            <div style={{ display: "flex", gap: "10px" }}>
              <input
                type="text"
                value={customerSearch}
                onChange={(e) => setCustomerSearch(e.target.value)}
                style={{ flex: 1, padding: "8px", border: "1px solid #ccc", borderRadius: "4px", fontSize: "14px" }}
              />
              <button type="submit" style={{ padding: "8px 16px", backgroundColor: "#008060", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer", fontSize: "14px" }}>Search</button>
            </div>
          </form>

          {selectedCustomer && (
            <div style={{ padding: "10px", backgroundColor: "#e8f5ff", border: "1px solid #b3d9ff", borderRadius: "4px", marginBottom: "15px", fontSize: "14px" }}>
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
                      padding: "12px",
                      border: "1px solid #ddd",
                      borderRadius: "4px",
                      marginBottom: "8px",
                      cursor: "pointer",
                      backgroundColor: selectedCustomer?.id === node.id ? "#f0f9ff" : "#fff",
                    }}
                  >
                    <div style={{ fontWeight: "bold", marginBottom: "4px" }}>{node.firstName} {node.lastName}</div>
                    <div style={{ fontSize: "13px", color: "#666" }}>{node.email}</div>
                    {node.phone && <div style={{ fontSize: "13px", color: "#666" }}>{node.phone}</div>}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div style={{ border: "1px solid #ddd", borderRadius: "8px", padding: "20px", backgroundColor: "#fff" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "15px" }}>
            <h2 style={{ fontSize: "18px", margin: 0 }}>Select Cable</h2>
            {scannerActive && (
              <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "#008060", fontSize: "14px", fontWeight: "bold" }}>
                <div style={{ width: "8px", height: "8px", borderRadius: "50%", backgroundColor: "#008060", animation: "pulse 1s infinite" }}></div>
                Scanner Active
              </div>
            )}
          </div>

          <form onSubmit={handleCableSearch} style={{ marginBottom: "15px" }}>
            <label style={{ display: "block", marginBottom: "5px", fontSize: "14px" }}>Search by serial number</label>
            <div style={{ display: "flex", gap: "10px" }}>
              <input
                type="text"
                value={cableSearch}
                onChange={(e) => setCableSearch(e.target.value)}
                onFocus={() => setCableInputFocused(true)}
                onBlur={() => setCableInputFocused(false)}
                style={{
                  flex: 1,
                  padding: "8px",
                  border: scannerActive ? "2px solid #008060" : "1px solid #ccc",
                  borderRadius: "4px",
                  fontSize: "14px",
                  backgroundColor: scannerActive ? "#f0f9ff" : "#fff",
                }}
              />
              <button type="submit" style={{ padding: "8px 16px", backgroundColor: "#008060", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer", fontSize: "14px" }}>Search</button>
            </div>
          </form>

          {selectedCable && (
            <div style={{ padding: "10px", backgroundColor: "#e8f5ff", border: "1px solid #b3d9ff", borderRadius: "4px", marginBottom: "15px", fontSize: "14px" }}>
              Selected: {selectedCable.serial_number} ({selectedCable.sku})
              {selectedCable.customer && (
                <div style={{ color: "#ff8c00", marginTop: "4px" }}>
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
                    padding: "12px",
                    border: "1px solid #ddd",
                    borderRadius: "4px",
                    marginBottom: "8px",
                    cursor: "pointer",
                    backgroundColor: selectedCable?.serial_number === item.serial_number ? "#f0f9ff" : "#fff",
                  }}
                >
                  <div style={{ fontWeight: "bold", marginBottom: "4px" }}>{item.serial_number}</div>
                  <div style={{ fontSize: "13px", color: "#666" }}>SKU: {item.sku}</div>
                  {item.series && <div style={{ fontSize: "13px", color: "#666" }}>Series: {item.series}</div>}
                  {item.customer && (
                    <div style={{ fontSize: "13px", color: "#ff8c00", marginTop: "4px" }}>
                      ⚠️ Already assigned to {item.customer.firstName} {item.customer.lastName}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div style={{ border: "1px solid #ddd", borderRadius: "8px", padding: "20px", backgroundColor: "#fff", textAlign: "center" }}>
        <button
          onClick={handleAssign}
          disabled={!selectedCustomer || !selectedCable}
          style={{
            padding: "12px 24px",
            backgroundColor: !selectedCustomer || !selectedCable ? "#ccc" : "#008060",
            color: "#fff",
            border: "none",
            borderRadius: "4px",
            cursor: !selectedCustomer || !selectedCable ? "not-allowed" : "pointer",
            fontSize: "16px",
            fontWeight: "bold",
          }}
        >
          Assign Cable to Customer
        </button>
      </div>
    </div>
  );
}
