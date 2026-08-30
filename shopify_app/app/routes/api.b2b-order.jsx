/**
 * POST /api/b2b-order  (called cross-origin by the customer-account extension)
 *
 * Body: { companyLocationId, lines: [{ variantId, quantity }], poNumber?, note? }
 * Header: Authorization: Bearer <extension session token>
 *
 * Creates a B2B draft order for the buyer's company location (wholesale pricing
 * applied by Shopify via the purchasing entity) and returns the order name +
 * invoice URL. Prices are never taken from the client.
 */
import { json } from "@remix-run/node";
import {
  verifyCustomerAccountToken,
  resolvePurchasingCompany,
  createWholesaleDraftOrder,
  HttpError,
} from "../b2b.server";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Authorization, Content-Type",
  "Access-Control-Max-Age": "86400",
};
const corsJson = (data, status = 200) => json(data, { status, headers: CORS_HEADERS });

const COMPANY_LOCATION_GID = /^gid:\/\/shopify\/CompanyLocation\/\d+$/;
const VARIANT_GID = /^gid:\/\/shopify\/ProductVariant\/\d+$/;
const MAX_LINES = 500;
const MAX_QTY = 9999;
const MAX_TEXT = 500;

function cleanText(value) {
  return String(value || "").trim().slice(0, MAX_TEXT);
}

export async function action({ request }) {
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }
  if (request.method !== "POST") {
    return corsJson({ error: "POST required" }, 405);
  }

  try {
    const { customerId } = verifyCustomerAccountToken(request);

    let body;
    try {
      body = await request.json();
    } catch {
      return corsJson({ error: "Invalid JSON body" }, 400);
    }

    const companyLocationId = String(body?.companyLocationId || "");
    if (!COMPANY_LOCATION_GID.test(companyLocationId)) {
      return corsJson({ error: "A valid companyLocationId is required" }, 400);
    }

    // Validate line items before touching Shopify.
    const rawLines = Array.isArray(body?.lines) ? body.lines : [];
    if (rawLines.length === 0) {
      return corsJson({ error: "Add at least one cable to your order" }, 400);
    }
    if (rawLines.length > MAX_LINES) {
      return corsJson({ error: "Too many line items" }, 400);
    }
    const lines = [];
    for (const l of rawLines) {
      if (!VARIANT_GID.test(l?.variantId)) {
        return corsJson({ error: "Invalid product in order" }, 400);
      }
      const quantity = Number(l?.quantity);
      if (!Number.isInteger(quantity) || quantity < 1 || quantity > MAX_QTY) {
        return corsJson({ error: "Invalid quantity in order" }, 400);
      }
      lines.push({ variantId: l.variantId, quantity });
    }

    // Confirms the customer may buy for this location and yields the purchasing
    // entity (company + contact) that drives B2B pricing on the draft order.
    const purchasingCompany = await resolvePurchasingCompany(customerId, companyLocationId);

    const result = await createWholesaleDraftOrder({
      purchasingCompany,
      lines,
      poNumber: cleanText(body?.poNumber),
      note: cleanText(body?.note),
    });

    return corsJson(result);
  } catch (err) {
    const status = err instanceof HttpError ? err.status : 500;
    if (status >= 500) console.error("b2b-order error:", err);
    return corsJson({ error: err.message || "Server error" }, status);
  }
}

export async function loader() {
  return corsJson({ error: "POST required" }, 405);
}
