import { json } from "@remix-run/node";
import { useLoaderData, useSearchParams, useLocation, Link } from "@remix-run/react";
import { authenticate } from "../shopify.server";
import { query } from "../db.server";
import { parseSku } from "../cable-config.server";

export async function loader({ request }) {
  await authenticate.admin(request);

  const url = new URL(request.url);
  const filter = url.searchParams.get("filter") || "active"; // active | archived | all

  const where = ["cs.sku ~ '-LTD-[A-Z0-9]{4,12}$'"];
  if (filter === "active") where.push("lm.archived_at IS NULL");
  else if (filter === "archived") where.push("lm.archived_at IS NOT NULL");

  const result = await query(
    `SELECT cs.sku, cs.length, cs.description,
            lm.event_name, lm.archived_at, lm.created_at,
            (SELECT COUNT(*) FROM audio_cables ac WHERE ac.sku = cs.sku) AS cable_count
     FROM cable_skus cs
     JOIN cable_ltd_metadata lm ON lm.sku = cs.sku
     WHERE ${where.join(" AND ")}
     ORDER BY (lm.archived_at IS NULL) DESC, lm.created_at DESC`
  );

  const editions = result.rows.map((r) => {
    const parsed = parseSku(r.sku);
    return {
      sku: r.sku,
      slug: parsed.slug ?? r.sku.split("-").slice(-1)[0],
      series: parsed.series,
      length: r.length,
      description: r.description,
      event_name: r.event_name,
      active: r.archived_at === null,
      archived_at: r.archived_at,
      created_at: r.created_at,
      cable_count: parseInt(r.cable_count, 10),
    };
  });

  return json({ editions, filter });
}

const TAB_STYLE_BASE = {
  padding: "8px 16px",
  border: "1px solid #ddd",
  borderRadius: "4px",
  cursor: "pointer",
  fontSize: "14px",
  textDecoration: "none",
  color: "#333",
  backgroundColor: "#fff",
};
const TAB_STYLE_ACTIVE = {
  ...TAB_STYLE_BASE,
  backgroundColor: "#008060",
  color: "#fff",
  border: "none",
  fontWeight: "bold",
};

export default function EditionsIndex() {
  const { editions, filter } = useLoaderData();
  const [searchParams] = useSearchParams();
  const location = useLocation();
  // Preserve current search params (notably `host`) on every Link so the
  // parent app.jsx loader's authenticate.admin call can resolve in-iframe.
  const linkTo = (pathname, extraParams = {}) => {
    const sp = new URLSearchParams(location.search);
    for (const [k, v] of Object.entries(extraParams)) sp.set(k, v);
    return { pathname, search: sp.toString() ? `?${sp.toString()}` : "" };
  };
  const qs = (f) => linkTo(location.pathname, { filter: f });

  return (
    <div style={{ padding: "20px", maxWidth: "1200px", margin: "0 auto", fontFamily: "system-ui, -apple-system, sans-serif" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
        <h1 style={{ fontSize: "24px", margin: 0 }}>Limited Editions</h1>
        <Link
          to={linkTo("/app/editions/new")}
          style={{
            padding: "10px 20px",
            backgroundColor: "#008060",
            color: "#fff",
            border: "none",
            borderRadius: "4px",
            fontSize: "14px",
            fontWeight: "bold",
            textDecoration: "none",
          }}
        >
          + New Edition
        </Link>
      </div>

      <div style={{ display: "flex", gap: "10px", marginBottom: "20px" }}>
        <Link to={qs("active")} style={filter === "active" ? TAB_STYLE_ACTIVE : TAB_STYLE_BASE}>
          Active
        </Link>
        <Link to={qs("archived")} style={filter === "archived" ? TAB_STYLE_ACTIVE : TAB_STYLE_BASE}>
          Archived
        </Link>
        <Link to={qs("all")} style={filter === "all" ? TAB_STYLE_ACTIVE : TAB_STYLE_BASE}>
          All
        </Link>
      </div>

      {editions.length === 0 ? (
        <div style={{ padding: "40px", textAlign: "center", backgroundColor: "#f5f5f5", borderRadius: "8px", color: "#666" }}>
          {filter === "archived" ? "No archived editions." : filter === "active" ? "No active editions. Create one to get started." : "No editions yet."}
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "14px" }}>
            <thead>
              <tr style={{ backgroundColor: "#f5f5f5" }}>
                <th style={{ padding: "12px", textAlign: "left", borderBottom: "2px solid #ddd" }}>SKU</th>
                <th style={{ padding: "12px", textAlign: "left", borderBottom: "2px solid #ddd" }}>Event</th>
                <th style={{ padding: "12px", textAlign: "left", borderBottom: "2px solid #ddd" }}>Series</th>
                <th style={{ padding: "12px", textAlign: "left", borderBottom: "2px solid #ddd" }}>Length</th>
                <th style={{ padding: "12px", textAlign: "right", borderBottom: "2px solid #ddd" }}>Cables</th>
                <th style={{ padding: "12px", textAlign: "left", borderBottom: "2px solid #ddd" }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {editions.map((e) => (
                <tr key={e.sku} style={{ backgroundColor: e.active ? "#fff" : "#fafafa" }}>
                  <td style={{ padding: "12px", borderBottom: "1px solid #eee", fontWeight: "bold" }}>
                    <Link to={linkTo(`/app/editions/${encodeURIComponent(e.sku)}`)} style={{ color: "#008060", textDecoration: "none" }}>
                      {e.sku}
                    </Link>
                  </td>
                  <td style={{ padding: "12px", borderBottom: "1px solid #eee" }}>{e.event_name}</td>
                  <td style={{ padding: "12px", borderBottom: "1px solid #eee", color: "#666" }}>{e.series}</td>
                  <td style={{ padding: "12px", borderBottom: "1px solid #eee", color: "#666" }}>{e.length}ft</td>
                  <td style={{ padding: "12px", borderBottom: "1px solid #eee", textAlign: "right", fontWeight: "bold" }}>{e.cable_count}</td>
                  <td style={{ padding: "12px", borderBottom: "1px solid #eee" }}>
                    <span style={{
                      padding: "4px 8px",
                      borderRadius: "12px",
                      fontSize: "12px",
                      fontWeight: "bold",
                      backgroundColor: e.active ? "#d4edda" : "#e2e3e5",
                      color: e.active ? "#155724" : "#6c757d",
                    }}>
                      {e.active ? "Active" : "Archived"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
