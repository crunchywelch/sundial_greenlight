import { json } from "@remix-run/node";
import { Outlet } from "@remix-run/react";
import { authenticate } from "../shopify.server";
import { TabBar } from "../components/TabBar";

export const loader = async ({ request }) => {
  await authenticate.admin(request);
  return json({ apiKey: process.env.SHOPIFY_API_KEY || "" });
};

const PULSE_KEYFRAMES = `@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }`;

/**
 * Shared layout for every /app/* route. Renders the top tab bar and a
 * shared @keyframes block (used by the scanner-active pulse indicator).
 * Each child route owns its own page padding/maxWidth so widths can vary
 * (e.g., editions detail is narrower than the inventory comparison table).
 */
export default function AppLayout() {
  return (
    <>
      <style>{PULSE_KEYFRAMES}</style>
      <div style={{ padding: "20px 20px 0", maxWidth: "1200px", margin: "0 auto", fontFamily: "system-ui, -apple-system, sans-serif" }}>
        <TabBar />
      </div>
      <Outlet />
    </>
  );
}
