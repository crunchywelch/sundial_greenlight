import { json } from "@remix-run/node";
import { query } from "../db.server.js";

// CORS is handled by nginx for all /api/ routes.

// GET - Look up a cable by registration code (public, no auth)
export async function loader({ request }) {
  const url = new URL(request.url);
  const code = url.searchParams.get("code");

  if (!code) {
    return json({ error: "Registration code is required" }, { status: 400 });
  }

  // Normalize: uppercase and trim
  const normalizedCode = code.trim().toUpperCase();

  try {
    const result = await query(
      `SELECT
        ac.serial_number,
        ac.sku,
        ac.registration_code,
        ac.shopify_gid,
        ac.test_passed,
        ac.test_timestamp,
        cs.series,
        cs.color_pattern,
        cs.connector_type,
        cs.core_cable,
        cs.length
      FROM audio_cables ac
      LEFT JOIN cable_skus cs ON ac.sku = cs.sku
      WHERE ac.registration_code = $1`,
      [normalizedCode]
    );

    if (result.rows.length === 0) {
      return json(
        { error: "Invalid registration code", code: "NOT_FOUND" },
        { status: 404 }
      );
    }

    const row = result.rows[0];

    // Check if already registered to a customer
    if (row.shopify_gid && row.shopify_gid !== "") {
      return json(
        { error: "This cable has already been registered", code: "ALREADY_REGISTERED" },
        { status: 409 }
      );
    }

    return json({
      cable: {
        serial_number: row.serial_number,
        sku: row.sku,
        series: row.series,
        color: row.color_pattern,
        connector_type: row.connector_type,
        core_cable: row.core_cable,
        length: row.length,
        test_passed: row.test_passed,
        test_date: row.test_timestamp,
      },
    });
  } catch (error) {
    console.error("Error looking up registration code:", error);
    return json({ error: "Failed to look up cable" }, { status: 500 });
  }
}

// POST - Register a cable to a customer
export async function action({ request }) {
  if (request.method !== "POST") {
    return json({ error: "Method not allowed" }, { status: 405 });
  }

  try {
    const body = await request.json();
    const { code, customerId, marketingOptIn } = body;

    if (!code || !customerId) {
      return json(
        { error: "code and customerId are required" },
        { status: 400 }
      );
    }

    const normalizedCode = code.trim().toUpperCase();

    // Look up the cable and verify it's not already registered
    const lookupResult = await query(
      `SELECT serial_number, sku, shopify_gid, registration_code
       FROM audio_cables
       WHERE registration_code = $1`,
      [normalizedCode]
    );

    if (lookupResult.rows.length === 0) {
      return json(
        { error: "Invalid registration code", code: "NOT_FOUND" },
        { status: 404 }
      );
    }

    const cable = lookupResult.rows[0];

    if (cable.shopify_gid && cable.shopify_gid !== "") {
      return json(
        { error: "This cable has already been registered", code: "ALREADY_REGISTERED" },
        { status: 409 }
      );
    }

    // Assign the cable to the customer
    await query(
      `UPDATE audio_cables
       SET shopify_gid = $1, updated_timestamp = NOW()
       WHERE registration_code = $2 AND (shopify_gid IS NULL OR shopify_gid = '')`,
      [customerId, normalizedCode]
    );

    // Handle marketing opt-in via Shopify Admin API if requested
    if (marketingOptIn) {
      try {
        await updateMarketingConsent(customerId);
      } catch (err) {
        // Don't fail the registration if marketing update fails
        console.error("Failed to update marketing consent:", err);
      }
    }

    return json({
      success: true,
      cable: {
        serial_number: cable.serial_number,
        sku: cable.sku,
      },
    });
  } catch (error) {
    console.error("Cable registration error:", error);
    return json({ error: error.message }, { status: 500 });
  }
}

async function updateMarketingConsent(customerId) {
  // Import shopify auth to make admin API calls
  const { authenticate } = await import("../shopify.server.js");

  // We need an offline session to make admin API calls from a public endpoint.
  // Use the shop's offline token stored in the session table.
  const { query: dbQuery } = await import("../db.server.js");
  const sessionResult = await dbQuery(
    `SELECT shop, access_token FROM shopify_sessions
     WHERE is_online = false AND access_token IS NOT NULL
     LIMIT 1`
  );

  if (sessionResult.rows.length === 0) {
    throw new Error("No offline session found");
  }

  const { shop, access_token } = sessionResult.rows[0];

  // Make a direct GraphQL call to update marketing consent
  const response = await fetch(
    `https://${shop}/admin/api/2025-07/graphql.json`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": access_token,
      },
      body: JSON.stringify({
        query: `mutation customerEmailMarketingConsentUpdate($input: CustomerEmailMarketingConsentUpdateInput!) {
          customerEmailMarketingConsentUpdate(input: $input) {
            customer { id }
            userErrors { field message }
          }
        }`,
        variables: {
          input: {
            customerId: customerId,
            emailMarketingConsent: {
              marketingOptInLevel: "SINGLE_OPT_IN",
              marketingState: "SUBSCRIBED",
              consentUpdatedAt: new Date().toISOString(),
            },
          },
        },
      }),
    }
  );

  const result = await response.json();
  if (result.data?.customerEmailMarketingConsentUpdate?.userErrors?.length > 0) {
    console.error(
      "Marketing consent errors:",
      result.data.customerEmailMarketingConsentUpdate.userErrors
    );
  }
}
