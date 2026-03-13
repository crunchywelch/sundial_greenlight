// Polling endpoint for scanner events (SSE blocked in Shopify iframe)
// - GET: React polls this to get latest scan for a specific Shopify user
// - POST: Greenlight scanner daemon sends scans here, tagged with shopifyUserId

// In-memory store keyed by Shopify user ID
let lastScanEvents = {};

// Export for use by other routes (e.g., order-fulfillment)
export function getLastScanEvent(shopifyUserId) {
  if (!shopifyUserId) return null;
  return lastScanEvents[shopifyUserId] || null;
}

// POST endpoint - scanner daemon sends scans here
export async function action({ request }) {
  if (request.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  try {
    // Get raw body text first to clean it
    const bodyText = await request.text();

    // Parse JSON, handling potential control characters
    let data;
    try {
      data = JSON.parse(bodyText);
    } catch (jsonError) {
      // Try cleaning the body text of control characters
      const cleanedBody = bodyText.replace(/[\x00-\x1F\x7F]/g, '');
      console.log("Cleaned body:", cleanedBody);
      data = JSON.parse(cleanedBody);
    }

    // Clean and validate the serial number
    let serial = data.serial;
    if (!serial) {
      return new Response(JSON.stringify({ error: "Missing serial" }), {
        status: 400,
        headers: {
          "Content-Type": "application/json",
          "Access-Control-Allow-Origin": "*"
        },
      });
    }

    // Trim whitespace and control characters
    serial = serial.trim().replace(/[\x00-\x1F\x7F]/g, '');

    const shopifyUserId = data.shopifyUserId ? String(data.shopifyUserId) : null;

    // Store the scan event keyed by Shopify user ID
    const event = {
      serial,
      timestamp: Date.now()
    };

    if (shopifyUserId) {
      lastScanEvents[shopifyUserId] = event;
      console.log(`Scanner event stored for user ${shopifyUserId}: "${serial}" at ${event.timestamp}`);
    } else {
      // Fallback: store under a default key for backward compatibility
      lastScanEvents["_default"] = event;
      console.log(`Scanner event stored (no user): "${serial}" at ${event.timestamp}`);
    }

    return new Response(JSON.stringify({ success: true, serial }), {
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*"
      },
    });
  } catch (error) {
    console.error("Scanner event error:", error);
    return new Response(JSON.stringify({ error: error.message }), {
      status: 500,
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*"
      },
    });
  }
}

// GET endpoint - React polls this to get latest scan for a specific user
export async function loader({ request }) {
  const url = new URL(request.url);
  const since = parseInt(url.searchParams.get("since") || "0");
  const shopifyUserId = url.searchParams.get("shopifyUserId") || "_default";

  // Expire scans after 5 seconds (so they don't reappear on page reload)
  const now = Date.now();
  const SCAN_TTL = 5000; // 5 seconds

  const event = lastScanEvents[shopifyUserId];

  // Return the scan event if it's newer than what the client has seen
  // and hasn't expired
  if (event &&
      event.timestamp > since &&
      (now - event.timestamp) < SCAN_TTL) {
    return new Response(JSON.stringify(event), {
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
      },
    });
  }

  // Return empty response if no new events
  return new Response(JSON.stringify({}), {
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
    },
  });
}

// CORS preflight
export async function options() {
  return new Response(null, {
    status: 204,
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    },
  });
}
