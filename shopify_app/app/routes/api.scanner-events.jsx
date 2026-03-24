// Scanner events endpoint - now backed by MQTT subscriptions instead of webhooks
// - GET: React polls this to get latest scan and scanner status

import { getLastScanEvent, getScannerStatus, getActiveGreenlightHosts } from "../mqtt.server.js";

// Re-export for use by other routes (e.g., order-fulfillment)
export { getLastScanEvent };

// GET endpoint - React polls this to get latest scan
export async function loader({ request }) {
  const url = new URL(request.url);
  const since = parseInt(url.searchParams.get("since") || "0");

  // If requesting scanner status
  if (url.searchParams.has("status")) {
    return new Response(
      JSON.stringify({
        hosts: getScannerStatus(),
        greenlightActive: getActiveGreenlightHosts(),
      }),
      {
        headers: {
          "Content-Type": "application/json",
          "Access-Control-Allow-Origin": "*",
        },
      },
    );
  }

  // Expire scans after 5 seconds (so they don't reappear on page reload)
  const now = Date.now();
  const SCAN_TTL = 5000;

  const lastScanEvent = getLastScanEvent();

  // Return the last scan event if it's newer than what the client has seen
  // and hasn't expired
  if (
    lastScanEvent &&
    lastScanEvent.timestamp > since &&
    now - lastScanEvent.timestamp < SCAN_TTL
  ) {
    return new Response(JSON.stringify(lastScanEvent), {
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
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    },
  });
}
