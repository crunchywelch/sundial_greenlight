import { json } from "@remix-run/node";
import { query, getClient, recordCableEvent } from "../db.server.js";
import { getLastScanEvent } from "../mqtt.server.js";
import { getActiveGreenlightHosts } from "../mqtt.server.js";
import {
  parseGroupSku,
  parseVariantSku,
  formatVariantSku,
  seriesForPrefix,
  seriesDataForPrefix,
} from "../cable-config.server.js";

function buildCableDisplay(row) {
  const parsed = parseGroupSku(row.sku_group);
  const seriesData = seriesDataForPrefix(row.prefix);
  const connectorDisplay =
    seriesData?.connectors?.find((c) => (c.code ?? "") === (row.connector_code ?? ""))?.display ?? null;
  return {
    sku: formatVariantSku({
      prefix: row.prefix,
      group_sku: row.sku_group,
      length: Number(row.length),
      connector_code: row.connector_code,
    }),
    sku_group: row.sku_group,
    prefix: row.prefix,
    series: seriesForPrefix(row.prefix),
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
        ac.prefix,
        ac.length,
        ac.connector_code,
        ac.test_passed,
        ac.test_timestamp,
        ac.shopify_gid,
        ac.shopify_order_gid,
        ac.wholesale_company_gid,
        ac.wholesale_location_gid
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
      wholesale_company_gid: row.wholesale_company_gid,
      wholesale_location_gid: row.wholesale_location_gid,
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
      ac.prefix,
      ac.length,
      ac.connector_code,
      ac.shopify_gid,
      ac.shopify_order_gid,
      ac.wholesale_company_gid,
      ac.wholesale_location_gid,
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
      wholesale_company_gid: row.wholesale_company_gid,
      wholesale_location_gid: row.wholesale_location_gid,
      test_passed: row.test_passed,
    },
  });
}

// Retail vs wholesale is decided by which identity the order carries: a B2B
// order has a company (purchasingEntity = PurchasingCompany) and no meaningful
// end customer; a retail order has a customer. This mirrors greenlight's
// assign_cable_to_order — shopify_gid means the END OWNER, so a B2B assign
// records the dealer and leaves shopify_gid NULL for the buyer to register later.
async function handleAssignCable({ serialNumber, orderId, customerId, companyId, companyLocationId, lineItemSkus }) {
  // A B2B assign has no end customer (the dealer company stands in); a retail
  // assign has no company. Require the order plus one of the two.
  if (!serialNumber || !orderId || (!customerId && !companyId)) {
    return json(
      { error: "serialNumber, orderId, and a customer or company are required" },
      { status: 400 }
    );
  }

  // Look up the cable
  const result = await query(
    `SELECT ac.serial_number, ac.sku_group, ac.prefix, ac.length, ac.connector_code,
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
    prefix: cable.prefix,
    group_sku: cable.sku_group,
    length: Number(cable.length),
    connector_code: cable.connector_code,
  });

  // shopify_gid means the end owner has already registered this cable. It can't
  // then be sold to a dealer — that would strand the buyer's registration.
  if (companyId && cable.shopify_gid && cable.shopify_gid !== "") {
    return json(
      { error: "Cable is registered to an end owner and cannot be assigned to a dealer", code: "ALREADY_REGISTERED" },
      { status: 409 }
    );
  }

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

  // The mutation and its audit event commit together (or roll back together).
  const client = await getClient();
  try {
    await client.query("BEGIN");
    if (companyId) {
      // Wholesale: record the dealer; leave shopify_gid for the buyer to claim.
      await client.query(
        `UPDATE audio_cables
         SET wholesale_company_gid = $1, wholesale_location_gid = $2, shopify_order_gid = $3, updated_timestamp = NOW()
         WHERE serial_number = $4`,
        [companyId, companyLocationId ?? null, orderId, serialNumber]
      );
      await recordCableEvent(client, {
        serialNumber,
        event: "assigned_dealer",
        actor: "admin",
        detail: { from: null, to: companyId, location: companyLocationId ?? null, order: orderId, sku: cableVariantSku },
      });
    } else {
      await client.query(
        `UPDATE audio_cables
         SET shopify_gid = $1, shopify_order_gid = $2, updated_timestamp = NOW()
         WHERE serial_number = $3`,
        [customerId, orderId, serialNumber]
      );
      await recordCableEvent(client, {
        serialNumber,
        event: "assigned_customer",
        actor: "admin",
        detail: { from: null, to: customerId, order: orderId, sku: cableVariantSku },
      });
    }
    await client.query("COMMIT");
  } catch (err) {
    await client.query("ROLLBACK");
    throw err;
  } finally {
    client.release();
  }

  return json({
    success: true,
    channel: companyId ? "wholesale" : "retail",
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

  // A cable can be committed to both channels at once (sold to a dealer, then
  // registered by the buyer who bought it from that dealer), so releasing one
  // must not destroy the other. The order gid belongs to whichever channel
  // bought the cable: if it carries a dealer, this is the wholesale order and we
  // release the dealer (keeping any end-owner registration); otherwise it's a
  // retail order and we release the owner. Mirrors greenlight unassign_cable.
  const found = await query(
    `SELECT shopify_gid, wholesale_company_gid FROM audio_cables
     WHERE serial_number = $1 AND shopify_order_gid = $2`,
    [serialNumber, orderId]
  );

  if (found.rows.length === 0) {
    return json(
      { error: "Cable not found or not assigned to this order" },
      { status: 404 }
    );
  }

  const { shopify_gid, wholesale_company_gid } = found.rows[0];

  const client = await getClient();
  try {
    await client.query("BEGIN");
    if (wholesale_company_gid) {
      await client.query(
        `UPDATE audio_cables
         SET wholesale_company_gid = NULL, wholesale_location_gid = NULL,
             shopify_order_gid = NULL, updated_timestamp = NOW()
         WHERE serial_number = $1 AND shopify_order_gid = $2`,
        [serialNumber, orderId]
      );
      await recordCableEvent(client, {
        serialNumber,
        event: "unassigned_dealer",
        actor: "admin",
        detail: { from: wholesale_company_gid, to: null, order: orderId },
      });
    } else {
      // Retail: no dealer on this cable, so the order is retail's — clear the
      // owner, its registration, and the order together.
      await client.query(
        `UPDATE audio_cables
         SET shopify_gid = NULL, registered_at = NULL,
             shopify_order_gid = NULL, updated_timestamp = NOW()
         WHERE serial_number = $1 AND shopify_order_gid = $2`,
        [serialNumber, orderId]
      );
      await recordCableEvent(client, {
        serialNumber,
        event: "unassigned_customer",
        actor: "admin",
        detail: { from: shopify_gid, to: null, order: orderId },
      });
    }
    await client.query("COMMIT");
  } catch (err) {
    await client.query("ROLLBACK");
    throw err;
  } finally {
    client.release();
  }

  return json({ success: true, channel: wholesale_company_gid ? "wholesale" : "retail" });
}
