import { json } from "@remix-run/node";
import { query } from "../db.server.js";
import { getLastScanEvent } from "../mqtt.server.js";
import { getActiveGreenlightHosts } from "../mqtt.server.js";
import {
  parseGroupSku,
  parseVariantSku,
  formatVariantSku,
  seriesDataForPrefix,
} from "../cable-config.server.js";

function buildCableDisplay(row) {
  const parsed = parseGroupSku(row.sku_group);
  const seriesData = parsed.prefix ? seriesDataForPrefix(parsed.prefix) : null;
  const connectorDisplay =
    seriesData?.connectors?.find((c) => (c.code ?? "") === (row.connector_code ?? ""))?.display ?? null;
  return {
    sku: formatVariantSku({
      group_sku: row.sku_group,
      length: Number(row.length),
      connector_code: row.connector_code,
    }),
    sku_group: row.sku_group,
    series: parsed.series,
    color: parsed.pattern_name ?? null,
    connector_type: connectorDisplay,
    length: Number(row.length),
  };
}

// CORS is handled by nginx for all /api/ routes — no app-level CORS headers needed.

// GET - Fetch cables assigned to an order, or poll scanner events
export async function loader({ request }) {
  const url = new URL(request.url);

  // Scanner event polling (proxied for admin extensions that can't use CORS)
  if (url.searchParams.has("since")) {
    const since = parseInt(url.searchParams.get("since") || "0");
    const SCAN_TTL = 5000;
    const now = Date.now();
    const lastScanEvent = getLastScanEvent();
    const greenlightActive = getActiveGreenlightHosts();

    const response = {};

    if (
      lastScanEvent &&
      lastScanEvent.timestamp > since &&
      now - lastScanEvent.timestamp < SCAN_TTL
    ) {
      response.serial = lastScanEvent.serial;
      response.timestamp = lastScanEvent.timestamp;
      response.host = lastScanEvent.host;
    }

    // Always include Greenlight status so the extension can show it
    if (greenlightActive.length > 0) {
      response.greenlightActive = greenlightActive;
    }

    return json(response);
  }

  const orderId = url.searchParams.get("orderId");

  if (!orderId) {
    return json({ error: "orderId is required" }, { status: 400 });
  }

  try {
    const result = await query(
      `SELECT
        ac.serial_number,
        ac.sku_group,
        ac.length,
        ac.connector_code,
        ac.test_passed,
        ac.test_timestamp,
        ac.shopify_gid,
        ac.shopify_order_gid
      FROM audio_cables ac
      WHERE ac.shopify_order_gid = $1
      ORDER BY ac.updated_timestamp DESC NULLS LAST`,
      [orderId]
    );

    const cables = result.rows.map((row) => ({
      serial_number: row.serial_number,
      ...buildCableDisplay(row),
      test_date: row.test_timestamp,
      test_passed: row.test_passed,
    }));

    return json({ cables });
  } catch (error) {
    console.error("Error fetching order cables:", error);
    return json({ error: "Failed to fetch cables" }, { status: 500 });
  }
}

// POST - assignCable, unassignCable, lookupCable
export async function action({ request }) {
  if (request.method !== "POST") {
    return json({ error: "Method not allowed" }, { status: 405 });
  }

  try {
    const body = await request.json();
    const { action } = body;

    if (action === "lookupCable") {
      return await handleLookupCable(body);
    }

    if (action === "assignCable") {
      return await handleAssignCable(body);
    }

    if (action === "unassignCable") {
      return await handleUnassignCable(body);
    }

    return json({ error: "Invalid action" }, { status: 400 });
  } catch (error) {
    console.error("Order fulfillment error:", error);
    return json({ error: error.message }, { status: 500 });
  }
}

async function handleLookupCable({ serialNumber }) {
  if (!serialNumber) {
    return json({ error: "serialNumber is required" }, { status: 400 });
  }

  const result = await query(
    `SELECT
      ac.serial_number,
      ac.sku_group,
      ac.length,
      ac.connector_code,
      ac.shopify_gid,
      ac.shopify_order_gid,
      ac.test_passed
    FROM audio_cables ac
    WHERE ac.serial_number = $1`,
    [serialNumber]
  );

  if (result.rows.length === 0) {
    return json({ error: "Cable not found", code: "NOT_FOUND" }, { status: 404 });
  }

  const row = result.rows[0];
  return json({
    cable: {
      serial_number: row.serial_number,
      ...buildCableDisplay(row),
      shopify_gid: row.shopify_gid,
      shopify_order_gid: row.shopify_order_gid,
      test_passed: row.test_passed,
    },
  });
}

async function handleAssignCable({ serialNumber, orderId, customerId, lineItemSkus }) {
  if (!serialNumber || !orderId || !customerId) {
    return json(
      { error: "serialNumber, orderId, and customerId are required" },
      { status: 400 }
    );
  }

  // Look up the cable
  const result = await query(
    `SELECT ac.serial_number, ac.sku_group, ac.length, ac.connector_code,
            ac.shopify_gid, ac.shopify_order_gid
     FROM audio_cables ac
     WHERE ac.serial_number = $1`,
    [serialNumber]
  );

  if (result.rows.length === 0) {
    return json({ error: "Cable not found", code: "NOT_FOUND" }, { status: 404 });
  }

  const cable = result.rows[0];
  const cableVariantSku = formatVariantSku({
    group_sku: cable.sku_group,
    length: Number(cable.length),
    connector_code: cable.connector_code,
  });

  if (cable.shopify_order_gid === orderId) {
    return json({ error: "Cable already scanned for this order", code: "DUPLICATE" }, { status: 409 });
  }

  if (cable.shopify_order_gid && cable.shopify_order_gid !== orderId) {
    return json({ error: "Cable is assigned to a different order", code: "ALREADY_ASSIGNED" }, { status: 409 });
  }

  // Match the cable's derived variant SKU against the order line item SKUs.
  if (lineItemSkus && lineItemSkus.length > 0) {
    const matches = lineItemSkus.some((sku) => sku === cableVariantSku);
    if (!matches) {
      return json(
        {
          error: `Cable SKU "${cableVariantSku}" does not match any line item in this order`,
          code: "SKU_MISMATCH",
          cableSku: cableVariantSku,
        },
        { status: 422 }
      );
    }
  }

  await query(
    `UPDATE audio_cables
     SET shopify_gid = $1, shopify_order_gid = $2, updated_timestamp = NOW()
     WHERE serial_number = $3`,
    [customerId, orderId, serialNumber]
  );

  return json({
    success: true,
    cable: { serial_number: serialNumber, sku: cableVariantSku },
  });
}

async function handleUnassignCable({ serialNumber, orderId }) {
  if (!serialNumber || !orderId) {
    return json(
      { error: "serialNumber and orderId are required" },
      { status: 400 }
    );
  }

  // Only unassign if it belongs to this order
  const result = await query(
    `UPDATE audio_cables
     SET shopify_gid = NULL, shopify_order_gid = NULL, updated_timestamp = NOW()
     WHERE serial_number = $1 AND shopify_order_gid = $2`,
    [serialNumber, orderId]
  );

  if (result.rowCount === 0) {
    return json(
      { error: "Cable not found or not assigned to this order" },
      { status: 404 }
    );
  }

  return json({ success: true });
}
