/**
 * Shared cable list table. Used by /app/cables/{sku_group} (canonical full
 * list) and the edition detail page's preview section.
 *
 * Each cable row needs at minimum: serial_number, variant_sku, length,
 * connector_code, test_passed, shopify_gid. Customer enrichment is
 * optional; if cable.customer is present (from an admin GraphQL lookup),
 * the row renders "First Last \n email"; if shopify_gid is set without a
 * resolved customer it shows "Unknown"; if no shopify_gid, "Available".
 */
export function CableTable({ cables }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "14px" }}>
        <thead>
          <tr style={{ backgroundColor: "#f5f5f5" }}>
            <th style={{ padding: "12px", textAlign: "left", borderBottom: "2px solid #ddd" }}>Serial Number</th>
            <th style={{ padding: "12px", textAlign: "left", borderBottom: "2px solid #ddd" }}>Variant SKU</th>
            <th style={{ padding: "12px", textAlign: "left", borderBottom: "2px solid #ddd" }}>Test Status</th>
            <th style={{ padding: "12px", textAlign: "left", borderBottom: "2px solid #ddd" }}>Assigned To</th>
          </tr>
        </thead>
        <tbody>
          {cables.map((cable) => {
            const isTested = cable.test_passed !== null && cable.test_passed !== undefined;
            return (
              <tr key={cable.serial_number} style={{ backgroundColor: "#fff" }}>
                <td style={{ padding: "12px", borderBottom: "1px solid #eee", fontWeight: "bold" }}>
                  {cable.serial_number}
                </td>
                <td style={{ padding: "12px", borderBottom: "1px solid #eee", color: "#666" }}>
                  <code>{cable.variant_sku}</code>
                  <div style={{ fontSize: "12px", color: "#999" }}>
                    {cable.length}ft{cable.connector_code === "-R" ? " · right angle" : ""}
                  </div>
                </td>
                <td style={{ padding: "12px", borderBottom: "1px solid #eee" }}>
                  <span style={{
                    padding: "4px 8px",
                    borderRadius: "12px",
                    fontSize: "12px",
                    fontWeight: "bold",
                    backgroundColor: isTested ? (cable.test_passed ? "#d4edda" : "#f8d7da") : "#fff3cd",
                    color: isTested ? (cable.test_passed ? "#155724" : "#721c24") : "#856404",
                  }}>
                    {isTested ? (cable.test_passed ? "Passed" : "Failed") : "Not Tested"}
                  </span>
                </td>
                <td style={{ padding: "12px", borderBottom: "1px solid #eee" }}>
                  {cable.customer ? (
                    <div>
                      <div style={{ fontWeight: "bold" }}>
                        {cable.customer.firstName} {cable.customer.lastName}
                      </div>
                      <div style={{ fontSize: "12px", color: "#666" }}>{cable.customer.email}</div>
                    </div>
                  ) : cable.shopify_gid ? (
                    <span style={{ color: "#999" }}>Unknown</span>
                  ) : (
                    <span style={{ color: "#008060", fontStyle: "italic" }}>Available</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
