import { json } from "@remix-run/node";
import { query } from "../db.server.js";
import { parseGroupSku, seriesDataForPrefix, formatVariantSku } from "../cable-config.server.js";

// CORS is handled by nginx for all /api/ routes.

// GET - Look up a cable by registration code (public, no auth)
export async function loader({ request }) {
  const url = new URL(request.url);
  const code = url.searchParams.get("code");

  if (!code) {
    return json({ error: "Registration code is required" }, { status: 400 });
  }

  const normalizedCode = code.trim().toUpperCase();

  try {
    const result = await query(
      `SELECT
        ac.serial_number,
        ac.sku_group,
        ac.length,
        ac.connector_code,
        ac.registration_code,
        ac.shopify_gid,
        ac.test_passed,
        ac.test_timestamp
      FROM audio_cables ac
      WHERE ac.registration_code = $1`,
      [normalizedCode]
    );

    if (result.rows.length === 0) {
      return json({ error: "Invalid registration code", code: "NOT_FOUND" }, { status: 404 });
    }

    const row = result.rows[0];

    if (row.shopify_gid && row.shopify_gid !== "") {
      return json({ error: "This cable has already been registered", code: "ALREADY_REGISTERED" }, { status: 409 });
    }

    const parsed = parseGroupSku(row.sku_group);
    const seriesData = parsed.prefix ? seriesDataForPrefix(parsed.prefix) : null;
    const connectorDisplay =
      seriesData?.connectors?.find((c) => (c.code ?? "") === (row.connector_code ?? ""))?.display ?? null;
    const variantSku = formatVariantSku({
      group_sku: row.sku_group,
      length: Number(row.length),
      connector_code: row.connector_code,
    });

    return json({
      cable: {
        serial_number: row.serial_number,
        sku: variantSku,
        sku_group: row.sku_group,
        series: parsed.series,
        color: parsed.pattern_name ?? null,
        connector_type: connectorDisplay,
        core_cable: seriesData?.core_cable ?? null,
        length: Number(row.length),
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
      return json({ error: "code and customerId are required" }, { status: 400 });
    }

    const normalizedCode = code.trim().toUpperCase();

    const lookupResult = await query(
      `SELECT serial_number, sku_group, shopify_gid, registration_code
       FROM audio_cables
       WHERE registration_code = $1`,
      [normalizedCode]
    );

    if (lookupResult.rows.length === 0) {
      return json({ error: "Invalid registration code", code: "NOT_FOUND" }, { status: 404 });
    }

    const cable = lookupResult.rows[0];

    if (cable.shopify_gid && cable.shopify_gid !== "") {
      return json({ error: "This cable has already been registered", code: "ALREADY_REGISTERED" }, { status: 409 });
    }

    await query(
      `UPDATE audio_cables
       SET shopify_gid = $1, updated_timestamp = NOW()
       WHERE registration_code = $2 AND (shopify_gid IS NULL OR shopify_gid = '')`,
      [customerId, normalizedCode]
    );

    if (marketingOptIn) {
      try {
        await updateMarketingConsent(customerId);
      } catch (err) {
        console.error("Failed to update marketing consent:", err);
      }
    }

    return json({
      success: true,
      cable: {
        serial_number: cable.serial_number,
        sku_group: cable.sku_group,
      },
    });
  } catch (error) {
    console.error("Cable registration error:", error);
    return json({ error: error.message }, { status: 500 });
  }
}

async function updateMarketingConsent(customerId) {
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
