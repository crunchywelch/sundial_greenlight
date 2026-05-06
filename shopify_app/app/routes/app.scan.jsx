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

    // Enrich with customer details for assigned cables
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
    console.error("Error searching cables:", error);
    return json({ error: "Failed to search cables" }, { status: 500 });
  }
}

export default function ScanCable() {
  const submit = useSubmit();
  const actionData = useActionData();
  const [cableSearch, setCableSearch] = useState("");
  const [scannerActive, setScannerActive] = useState(false);
  const [cableInputFocused, setCableInputFocused] = useState(false);

  const cables = actionData?.cables || [];
  const scanEvent = useScannerEvents(cableInputFocused);

  useEffect(() => {
    if (scanEvent?.serial) {
      setCableSearch(scanEvent.serial);
      setScannerActive(true);
      setTimeout(() => setScannerActive(false), 2000);
      const formData = new FormData();
      formData.append("searchTerm", scanEvent.serial);
      submit(formData, { method: "post" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scanEvent?.timestamp]);

  const handleCableSearch = (e) => {
    e.preventDefault();
    const formData = new FormData();
    formData.append("searchTerm", cableSearch);
    submit(formData, { method: "post" });
  };

  return (
    <div style={{ padding: "0 20px 20px", maxWidth: "1200px", margin: "0 auto", fontFamily: "system-ui, -apple-system, sans-serif" }}>
      <h1 style={{ fontSize: "24px", marginBottom: "20px" }}>Scan Cable</h1>

      <div style={{ border: "1px solid #ddd", borderRadius: "8px", padding: "20px", backgroundColor: "#fff", marginBottom: "20px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "15px" }}>
          <h2 style={{ fontSize: "18px", margin: 0 }}>Cable Lookup</h2>
          {scannerActive && (
            <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "#008060", fontSize: "14px", fontWeight: "bold" }}>
              <div style={{ width: "8px", height: "8px", borderRadius: "50%", backgroundColor: "#008060", animation: "pulse 1s infinite" }}></div>
              Scanner Active
            </div>
          )}
        </div>

        <form onSubmit={handleCableSearch} style={{ marginBottom: "20px" }}>
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
                padding: "10px",
                border: scannerActive ? "2px solid #008060" : "1px solid #ccc",
                borderRadius: "4px",
                fontSize: "16px",
                backgroundColor: scannerActive ? "#f0f9ff" : "#fff",
              }}
            />
            <button type="submit" style={{ padding: "10px 20px", backgroundColor: "#008060", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer", fontSize: "16px" }}>
              Search
            </button>
          </div>
        </form>

        {cables.length > 0 && (
          <div>
            <h3 style={{ fontSize: "16px", marginBottom: "10px" }}>Results:</h3>
            {cables.map((item) => (
              <div key={item.serial_number} style={{ padding: "15px", border: "1px solid #ddd", borderRadius: "4px", marginBottom: "10px", backgroundColor: "#fff" }}>
                <div style={{ fontWeight: "bold", fontSize: "18px", marginBottom: "8px" }}>{item.serial_number}</div>
                <div style={{ fontSize: "14px", color: "#666", marginBottom: "4px" }}>SKU: {item.sku}</div>
                {item.series && <div style={{ fontSize: "14px", color: "#666", marginBottom: "4px" }}>Series: {item.series}</div>}
                {item.sku_length && <div style={{ fontSize: "14px", color: "#666", marginBottom: "4px" }}>Length: {item.sku_length}ft</div>}

                {item.customer ? (
                  <div style={{ marginTop: "12px", padding: "10px", backgroundColor: "#f0f9ff", border: "1px solid #b3d9ff", borderRadius: "4px" }}>
                    <div style={{ fontSize: "14px", color: "#008060", fontWeight: "bold", marginBottom: "6px" }}>✓ Assigned to:</div>
                    <div style={{ fontSize: "14px", color: "#333", fontWeight: "bold" }}>{item.customer.firstName} {item.customer.lastName}</div>
                    {item.customer.email && <div style={{ fontSize: "13px", color: "#666" }}>{item.customer.email}</div>}
                    {item.customer.phone && <div style={{ fontSize: "13px", color: "#666" }}>{item.customer.phone}</div>}
                  </div>
                ) : item.shopify_gid ? (
                  <div style={{ fontSize: "14px", color: "#008060", marginTop: "8px", fontWeight: "bold" }}>✓ Assigned to customer</div>
                ) : (
                  <div style={{ fontSize: "14px", color: "#999", marginTop: "8px" }}>Not yet assigned</div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
