import { json } from "@remix-run/node";
import { query } from "../db.server.js";
import { getLastScanEvent } from "./api.scanner-events.jsx";

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

    if (
      lastScanEvent &&
      lastScanEvent.timestamp > since &&
      now - lastScanEvent.timestamp < SCAN_TTL
    ) {
      return json(lastScanEvent);
    }
    return json({});
  }

  const orderId = url.searchParams.get("orderId");

  if (!orderId) {
    return json({ error: "orderId is required" }, { status: 400 });
  }

  try {
    const result = await query(
      `SELECT
        ac.serial_number,
        ac.sku,
        ac.description,
        ac.length,
        ac.test_passed,
        ac.test_timestamp,
        ac.shopify_gid,
        ac.shopify_order_gid,
        cs.series,
        cs.color_pattern,
        cs.connector_type
      FROM audio_cables ac
      LEFT JOIN cable_skus cs ON ac.sku = cs.sku
      WHERE ac.shopify_order_gid = $1
      ORDER BY ac.test_timestamp DESC NULLS LAST`,
      [orderId]
    );

    const cables = result.rows.map((row) => ({
      serial_number: row.serial_number,
      sku: row.sku,
      description: row.description,
      length: row.length,
      series: row.series,
      color: row.color_pattern,
      connector_type: row.connector_type,
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
      ac.sku,
      ac.description,
      ac.length,
      ac.shopify_gid,
      ac.shopify_order_gid,
      ac.test_passed,
      cs.series,
      cs.color_pattern,
      cs.connector_type
    FROM audio_cables ac
    LEFT JOIN cable_skus cs ON ac.sku = cs.sku
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
      sku: row.sku,
      description: row.description,
      length: row.length,
      series: row.series,
      color: row.color_pattern,
      connector_type: row.connector_type,
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
    `SELECT ac.serial_number, ac.sku, ac.shopify_gid, ac.shopify_order_gid
     FROM audio_cables ac
     WHERE ac.serial_number = $1`,
    [serialNumber]
  );

  if (result.rows.length === 0) {
    return json(
      { error: "Cable not found", code: "NOT_FOUND" },
      { status: 404 }
    );
  }

  const cable = result.rows[0];

  // Check if already assigned to this order (duplicate scan)
  if (cable.shopify_order_gid === orderId) {
    return json(
      { error: "Cable already scanned for this order", code: "DUPLICATE" },
      { status: 409 }
    );
  }

  // Check if assigned to a different order
  if (cable.shopify_order_gid && cable.shopify_order_gid !== orderId) {
    return json(
      { error: "Cable is assigned to a different order", code: "ALREADY_ASSIGNED" },
      { status: 409 }
    );
  }

  // Check SKU matches a line item if lineItemSkus provided
  if (lineItemSkus && lineItemSkus.length > 0) {
    const cableSku = cable.sku;
    const matches = lineItemSkus.some((sku) => sku === cableSku);
    if (!matches) {
      return json(
        {
          error: `Cable SKU "${cableSku}" does not match any line item in this order`,
          code: "SKU_MISMATCH",
          cableSku,
        },
        { status: 422 }
      );
    }
  }

  // Assign the cable to the order and customer
  await query(
    `UPDATE audio_cables
     SET shopify_gid = $1, shopify_order_gid = $2, updated_timestamp = NOW()
     WHERE serial_number = $3`,
    [customerId, orderId, serialNumber]
  );

  return json({
    success: true,
    cable: { serial_number: serialNumber, sku: cable.sku },
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
     SET shopify_order_gid = NULL, updated_timestamp = NOW()
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
