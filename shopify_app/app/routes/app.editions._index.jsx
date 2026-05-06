import { json } from "@remix-run/node";
import { useLoaderData, useSearchParams, useLocation, Link } from "@remix-run/react";
import { authenticate } from "../shopify.server";
import { listEditions } from "../editions.server";

export async function loader({ request }) {
  await authenticate.admin(request);
  const url = new URL(request.url);
  const filter = url.searchParams.get("filter") || "active";
  const editions = await listEditions(filter);
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
        <Link to={qs("active")} style={filter === "active" ? TAB_STYLE_ACTIVE : TAB_STYLE_BASE}>Active</Link>
        <Link to={qs("archived")} style={filter === "archived" ? TAB_STYLE_ACTIVE : TAB_STYLE_BASE}>Archived</Link>
        <Link to={qs("all")} style={filter === "all" ? TAB_STYLE_ACTIVE : TAB_STYLE_BASE}>All</Link>
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
                <th style={{ padding: "12px", textAlign: "left", borderBottom: "2px solid #ddd" }}>Slug</th>
                <th style={{ padding: "12px", textAlign: "left", borderBottom: "2px solid #ddd" }}>Description</th>
                <th style={{ padding: "12px", textAlign: "right", borderBottom: "2px solid #ddd" }}>Cables</th>
                <th style={{ padding: "12px", textAlign: "left", borderBottom: "2px solid #ddd" }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {editions.map((e) => (
                <tr key={e.sku} style={{ backgroundColor: e.active ? "#fff" : "#fafafa" }}>
                  <td style={{ padding: "12px", borderBottom: "1px solid #eee", fontWeight: "bold" }}>
                    <Link to={linkTo(`/app/editions/${encodeURIComponent(e.sku)}`)} style={{ color: "#008060", textDecoration: "none" }}>
                      {e.slug}
                    </Link>
                    <div style={{ fontSize: "12px", fontWeight: "normal", color: "#999" }}>{e.sku}</div>
                  </td>
                  <td style={{ padding: "12px", borderBottom: "1px solid #eee" }}>{e.description}</td>
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
