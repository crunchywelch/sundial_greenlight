// SSE endpoint for real-time scanner events
// - GET: React connects here to receive scan events
// - POST: Greenlight sends scans here to broadcast

// In-memory store for connected SSE clients
const clients = new Set();

// POST endpoint - Greenlight sends scans here
export async function action({ request }) {
  if (request.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  const { serial } = await request.json();
  const event = `data: ${JSON.stringify({ serial, timestamp: Date.now() })}\n\n`;

  // Broadcast to all connected clients
  for (const client of clients) {
    try {
      client.enqueue(event);
    } catch {
      clients.delete(client);
    }
  }

  return new Response("ok", {
    headers: { "Access-Control-Allow-Origin": "*" },
  });
}

// GET endpoint - React connects here for SSE stream
export async function loader({ request }) {
  const stream = new ReadableStream({
    start(controller) {
      clients.add(controller);
      controller.enqueue(": connected\n\n");
    },
    cancel(controller) {
      clients.delete(controller);
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
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
