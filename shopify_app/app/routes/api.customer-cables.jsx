import { json } from "@remix-run/node";
import { query } from "../db.server.js";
import { parseGroupSku, seriesForPrefix, seriesDataForPrefix, formatVariantSku } from "../cable-config.server.js";

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

export async function loader({ request }) {
  const url = new URL(request.url);
  const customerId = url.searchParams.get("customerId");

  if (!customerId) {
    return json({ error: "Customer ID is required" }, { status: 400 });
  }

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
  const result = await query(
    `SELECT
      ac.serial_number,
      ac.sku_group,
      ac.prefix,
      ac.length,
      ac.connector_code,
      ac.test_passed,
      ac.test_timestamp,
      ac.operator,
      ac.shopify_gid,
      sg.description
    FROM audio_cables ac
    LEFT JOIN sku_group sg ON sg.sku = ac.sku_group
    WHERE ac.shopify_gid = $1
    ORDER BY ac.test_timestamp DESC NULLS LAST`,
    [customerId]
  );

  return result.rows.map((row) => {
    const parsed = parseGroupSku(row.sku_group);
    const seriesData = seriesDataForPrefix(row.prefix);
    const connectorDisplay =
      seriesData?.connectors?.find((c) => (c.code ?? "") === (row.connector_code ?? ""))?.display ?? null;
    const variantSku = formatVariantSku({
      prefix: row.prefix,
      group_sku: row.sku_group,
      length: Number(row.length),
      connector_code: row.connector_code,
    });
    const colorPattern = parsed.pattern_name ?? null;
    return {
      serial_number: row.serial_number,
      sku: variantSku,
      sku_group: row.sku_group,
      prefix: row.prefix,
      series: seriesForPrefix(row.prefix),
      color: colorPattern,
      connector_type: connectorDisplay,
      core_cable: seriesData?.core_cable ?? null,
      length: Number(row.length),
      description: row.description,
      test_date: row.test_timestamp,
      test_passed: row.test_passed,
      test_status: row.test_passed !== null ? "tested" : "not tested",
      operator: row.operator,
      image: getCableImageFilename(colorPattern),
    };
  });
}
