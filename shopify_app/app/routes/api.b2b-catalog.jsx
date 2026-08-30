/**
 * POST /api/b2b-catalog  (called cross-origin by the customer-account extension)
 *
 * Body: { companyLocationId }
 * Header: Authorization: Bearer <extension session token>
 * Returns the wholesale reorder grid (styles x length x connector) with per-cell
 * MSRP + wholesale price for the buyer's company location.
 *
 * CORS is handled by the nginx layer in front of the app (same as
 * /api/customer-cables); this route must NOT set its own Access-Control-* headers
 * or the duplicated Allow-Origin breaks the browser fetch.
 */
import { json } from "@remix-run/node";
import {
  verifyCustomerAccountToken,
  assertCustomerOwnsLocation,
  buildWholesaleCatalog,
  normalizeCompanyLocationId,
  HttpError,
} from "../b2b.server";

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

    await assertCustomerOwnsLocation(customerId, companyLocationId);
    const catalog = await buildWholesaleCatalog(companyLocationId);
    return json({ catalog });
  } catch (err) {
    const status = err instanceof HttpError ? err.status : 500;
    if (status >= 500) console.error("b2b-catalog error:", err);
    return json({ error: err.message || "Server error" }, { status });
  }
}

export async function loader() {
  return json({ error: "POST required" }, { status: 405 });
}
