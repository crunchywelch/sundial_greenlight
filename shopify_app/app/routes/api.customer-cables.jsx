import { json } from "@remix-run/node";

// This is a public API endpoint that the storefront can call
// Note: In production, you'll want to connect this to your actual database
export async function loader({ request }) {
  const url = new URL(request.url);
  const customerId = url.searchParams.get("customerId");

  if (!customerId) {
    return json({ error: "Customer ID is required" }, { status: 400 });
  }

  try {
    // TODO: Replace this with actual database query
    // For now, returning mock data
    const cables = await fetchCustomerCables(customerId);

    // Set CORS headers to allow storefront to access this endpoint
    return json(
      { cables },
      {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
        },
      }
    );
  } catch (error) {
    console.error("Error fetching customer cables:", error);
    return json(
      { error: "Failed to fetch cables" },
      {
        status: 500,
        headers: {
          "Access-Control-Allow-Origin": "*",
        },
      }
    );
  }
}

// Handle OPTIONS requests for CORS
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

// Mock function - replace with actual database query
async function fetchCustomerCables(customerId) {
  // TODO: Connect to your Greenlight PostgreSQL database
  // Example query (pseudocode):
  // const cables = await db.query(
  //   'SELECT * FROM audio_cables WHERE customer_id = $1',
  //   [customerId]
  // );

  // For now, return mock data
  return [
    {
      id: 1,
      name: "Premium XLR Cable",
      serial_number: "XLR-2024-001",
      cable_type: "XLR",
      length: "10ft",
      test_date: "2024-12-15",
      test_status: "passed",
    },
    {
      id: 2,
      name: "TRS Patch Cable",
      serial_number: "TRS-2024-042",
      cable_type: "TRS",
      length: "6ft",
      test_date: "2024-12-20",
      test_status: "passed",
    },
  ];
}
