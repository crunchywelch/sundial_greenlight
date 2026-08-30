/**
 * POST /api/b2b-catalog  (called cross-origin by the customer-account extension)
 *
 * Body: { companyLocationId }
 * Header: Authorization: Bearer <extension session token>
 * Returns the wholesale reorder grid (styles x length x connector) with per-cell
 * MSRP + wholesale price for the buyer's company location.
 */
import { json } from "@remix-run/node";
import {
  verifyCustomerAccountToken,
  assertCustomerOwnsLocation,
  buildWholesaleCatalog,
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

    await assertCustomerOwnsLocation(customerId, companyLocationId);
    const catalog = await buildWholesaleCatalog(companyLocationId);
    return corsJson({ catalog });
  } catch (err) {
    const status = err instanceof HttpError ? err.status : 500;
    if (status >= 500) console.error("b2b-catalog error:", err);
    return corsJson({ error: err.message || "Server error" }, status);
  }
}

// A stray GET (e.g. someone opening the URL) shouldn't 404 the route.
export async function loader() {
  return corsJson({ error: "POST required" }, 405);
}
