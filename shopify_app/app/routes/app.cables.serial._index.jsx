import { json } from "@remix-run/node";
import { authenticate } from "../shopify.server";
import { CableLookup } from "../components/CableLookup";

export async function loader({ request }) {
  await authenticate.admin(request);
  return json({});
}

export default function CableLookupLanding() {
  return (
    <div style={{ padding: "20px", maxWidth: "1100px", margin: "0 auto", fontFamily: "system-ui, -apple-system, sans-serif" }}>
      <h1 style={{ fontSize: "24px", margin: "0 0 16px" }}>Cable Lookup</h1>
      <CableLookup />
      <div style={{ padding: "40px", textAlign: "center", backgroundColor: "#f5f5f5", borderRadius: "8px", color: "#666", fontSize: "14px" }}>
        Scan a cable or type its serial number to view and manage it.
      </div>
    </div>
  );
}
