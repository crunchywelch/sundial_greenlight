/**
 * Shared cable list table. Used by /app/cables/{sku_group} (canonical full
 * list) and the edition detail page's preview section.
 *
 * Each cable row needs at minimum: serial_number, variant_sku, length,
 * connector_code, test_passed, shopify_gid. Optional: registration_code
 * (marks a cable allocated to a wholesale/reseller channel) and customer
 * (from an admin GraphQL lookup) which renders "First Last \n email".
 */

/**
 * Collapse a cable's flags into one mutually-exclusive lifecycle state.
 * Priority: shipped-to-customer > allocated-to-wholesale > QC outcome.
 * These are the same five buckets the inventory hub counts, so a row's
 * badge always agrees with the per-SKU tally.
 */
export function cableState(cable) {
  if (cable.shopify_gid) return "assigned";
  if (cable.registration_code) return "wholesale";
  if (cable.test_passed === true) return "retail";
  if (cable.test_passed === false) return "failed";
  return "untested";
}

export const STATE_META = {
  retail: { label: "Retail", bg: "#d4edda", fg: "#155724" },
  wholesale: { label: "Wholesale", bg: "#e7e0f7", fg: "#5c3d99" },
  assigned: { label: "Assigned", bg: "#d6e4ff", fg: "#1a3d7c" },
  failed: { label: "Failed", bg: "#f8d7da", fg: "#721c24" },
  untested: { label: "Untested", bg: "#fff3cd", fg: "#856404" },
};

function Badge({ bg, fg, children }) {
  return (
    <span style={{ padding: "4px 8px", borderRadius: "12px", fontSize: "12px", fontWeight: "bold", backgroundColor: bg, color: fg }}>
      {children}
    </span>
  );
}

export function CableTable({ cables }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "14px" }}>
        <thead>
          <tr style={{ backgroundColor: "#f5f5f5" }}>
            <th style={{ padding: "12px", textAlign: "left", borderBottom: "2px solid #ddd" }}>Serial Number</th>
            <th style={{ padding: "12px", textAlign: "left", borderBottom: "2px solid #ddd" }}>Variant SKU</th>
            <th style={{ padding: "12px", textAlign: "left", borderBottom: "2px solid #ddd" }}>Test</th>
            <th style={{ padding: "12px", textAlign: "left", borderBottom: "2px solid #ddd" }}>Status</th>
          </tr>
        </thead>
        <tbody>
          {cables.map((cable) => {
            const isTested = cable.test_passed !== null && cable.test_passed !== undefined;
            const state = cableState(cable);
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
                  <Badge
                    bg={isTested ? (cable.test_passed ? "#d4edda" : "#f8d7da") : "#fff3cd"}
                    fg={isTested ? (cable.test_passed ? "#155724" : "#721c24") : "#856404"}
                  >
                    {isTested ? (cable.test_passed ? "Passed" : "Failed") : "Not Tested"}
                  </Badge>
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
                    <span style={{ color: "#999" }}>Assigned (unknown customer)</span>
                  ) : state === "wholesale" ? (
                    <div>
                      <Badge bg={STATE_META.wholesale.bg} fg={STATE_META.wholesale.fg}>Wholesale</Badge>
                      <div style={{ fontSize: "12px", color: "#999", marginTop: "3px" }}>
                        <code>{cable.registration_code}</code>
                      </div>
                    </div>
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
