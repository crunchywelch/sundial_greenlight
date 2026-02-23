import { json } from "@remix-run/node";
import { query } from "../db.server.js";

// This is a public API endpoint that the storefront can call
export async function loader({ request }) {
  const url = new URL(request.url);
  const customerId = url.searchParams.get("customerId");

  if (!customerId) {
    return json({ error: "Customer ID is required" }, { status: 400 });
  }

  try {
    const cables = await fetchCustomerCables(customerId);

    return json({ cables });
  } catch (error) {
    console.error("Error fetching customer cables:", error);
    return json({ error: "Failed to fetch cables" }, { status: 500 });
  }
}

async function fetchCustomerCables(customerId) {
  // Query the database for cables associated with this customer
  // The schema uses serial_number as primary key and shopify_gid for customer association
  const result = await query(
    `SELECT
      ac.serial_number,
      ac.sku,
      ac.test_passed,
      ac.test_timestamp,
      ac.operator,
      ac.shopify_gid,
      cs.series,
      cs.color_pattern,
      cs.connector_type,
      cs.core_cable
    FROM audio_cables ac
    LEFT JOIN cable_skus cs ON ac.sku = cs.sku
    WHERE ac.shopify_gid = $1
    ORDER BY ac.test_timestamp DESC NULLS LAST`,
    [customerId]
  );

  return result.rows.map((row) => ({
    serial_number: row.serial_number,
    sku: row.sku,
    series: row.series,
    color: row.color_pattern,
    connector_type: row.connector_type,
    core_cable: row.core_cable,
    test_date: row.test_timestamp,
    test_passed: row.test_passed,
    test_status: row.test_passed !== null ? "tested" : "not tested",
    operator: row.operator,
  }));
}
