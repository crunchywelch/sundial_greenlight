import { json } from "@remix-run/node";
import { query } from "../db.server.js";
import { parseSku, seriesDataForPrefix } from "../cable-config.server.js";

const CABLE_IMAGE_MAP = {
  "goldline": "cable-goldline.png",
  "pearl white": "cable-pearl-white.png",
  "silverline": "cable-silverline.png",
  "bungalow": "cable-bungalow.png",
  "electric houndstooth": "cable-electric-houndstooth.png",
  "houndstooth putty": "cable-houndstooth-putty.png",
  "road stripe": "cable-road-stripe.png",
};
const DEFAULT_IMAGE = "cable-special-babies.png";

function getCableImageFilename(colorPattern) {
  return CABLE_IMAGE_MAP[(colorPattern || "").toLowerCase()] || DEFAULT_IMAGE;
}

// This is a public API endpoint that the storefront can call
export async function loader({ request }) {
  const url = new URL(request.url);
  const customerId = url.searchParams.get("customerId");

  if (!customerId) {
    return json({ error: "Customer ID is required" }, { status: 400 });
  }

  // Accept both raw numeric ID and full GID format
  const gid = customerId.startsWith("gid://")
    ? customerId
    : `gid://shopify/Customer/${customerId}`;

  try {
    const cables = await fetchCustomerCables(gid);

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
      cs.length AS variant_length
    FROM audio_cables ac
    LEFT JOIN cable_skus cs ON ac.sku = cs.sku
    WHERE ac.shopify_gid = $1
    ORDER BY ac.test_timestamp DESC NULLS LAST`,
    [customerId]
  );

  return result.rows.map((row) => {
    const parsed = parseSku(row.sku);
    const seriesData = parsed.series_prefix ? seriesDataForPrefix(parsed.series_prefix) : null;
    const length = parsed.kind === "catalog" ? parsed.length : row.variant_length;
    const colorPattern = parsed.pattern_name ?? null;
    return {
      serial_number: row.serial_number,
      sku: row.sku,
      series: parsed.series,
      color: colorPattern,
      connector_type: parsed.connector_display ?? null,
      core_cable: seriesData?.core_cable ?? null,
      length,
      test_date: row.test_timestamp,
      test_passed: row.test_passed,
      test_status: row.test_passed !== null ? "tested" : "not tested",
      operator: row.operator,
      image: getCableImageFilename(colorPattern),
    };
  });
}
