/**
 * POST /api/b2b-order  (called cross-origin by the customer-account extension)
 *
 * Body: { companyLocationId, lines: [{ variantId, quantity }], poNumber?, note? }
 * Header: Authorization: Bearer <extension session token>
 *
 * Creates a B2B draft order for the buyer's company location (wholesale pricing
 * applied by Shopify via the purchasing entity) and returns the order name +
 * invoice URL. Prices are never taken from the client.
 *
 * CORS is handled by the nginx layer in front of the app (same as
 * /api/customer-cables); this route must NOT set its own Access-Control-* headers.
 */
import { json } from "@remix-run/node";
import {
  verifyCustomerAccountToken,
  resolvePurchasingCompany,
  createWholesaleDraftOrder,
  normalizeCompanyLocationId,
  HttpError,
} from "../b2b.server";

const VARIANT_GID = /^gid:\/\/shopify\/ProductVariant\/\d+$/;
const MAX_LINES = 500;
const MAX_QTY = 9999;
const MAX_TEXT = 500;

function cleanText(value) {
  return String(value || "").trim().slice(0, MAX_TEXT);
}

export async function action({ request }) {
  if (request.method !== "POST") {
    return json({ error: "POST required" }, { status: 405 });
  }

  try {
    const { customerId } = verifyCustomerAccountToken(request);

    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: "Invalid JSON body" }, { status: 400 });
    }

    const companyLocationId = normalizeCompanyLocationId(body?.companyLocationId);
    if (!companyLocationId) {
      return json({ error: "A valid companyLocationId is required" }, { status: 400 });
    }

    const rawLines = Array.isArray(body?.lines) ? body.lines : [];
    if (rawLines.length === 0) {
      return json({ error: "Add at least one cable to your order" }, { status: 400 });
    }
    if (rawLines.length > MAX_LINES) {
      return json({ error: "Too many line items" }, { status: 400 });
    }
    const lines = [];
    for (const l of rawLines) {
      if (!VARIANT_GID.test(l?.variantId)) {
        return json({ error: "Invalid product in order" }, { status: 400 });
      }
      const quantity = Number(l?.quantity);
      if (!Number.isInteger(quantity) || quantity < 1 || quantity > MAX_QTY) {
        return json({ error: "Invalid quantity in order" }, { status: 400 });
      }
      lines.push({ variantId: l.variantId, quantity });
    }

    const purchasingCompany = await resolvePurchasingCompany(customerId, companyLocationId);

    const result = await createWholesaleDraftOrder({
      purchasingCompany,
      lines,
      poNumber: cleanText(body?.poNumber),
      note: cleanText(body?.note),
    });

    return json(result);
  } catch (err) {
    const status = err instanceof HttpError ? err.status : 500;
    if (status >= 500) console.error("b2b-order error:", err);
    return json({ error: err.message || "Server error" }, { status });
  }
}

export async function loader() {
  return json({ error: "POST required" }, { status: 405 });
}
