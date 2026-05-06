import { Link, useLocation } from "@remix-run/react";

const TABS = [
  { path: "/app/scan", label: "Scan Cable" },
  { path: "/app/assign", label: "Assign Cable" },
  { path: "/app/customers", label: "Customer Lookup" },
  { path: "/app/inventory", label: "Inventory" },
  { path: "/app/editions", label: "Editions", matchPrefix: "/app/editions" },
];

const STYLE_BASE = {
  padding: "10px 20px",
  backgroundColor: "#fff",
  color: "#333",
  border: "1px solid #ddd",
  borderRadius: "4px",
  cursor: "pointer",
  fontSize: "16px",
  textDecoration: "none",
  display: "inline-block",
};
const STYLE_ACTIVE = {
  ...STYLE_BASE,
  backgroundColor: "#008060",
  color: "#fff",
  border: "none",
  fontWeight: "bold",
};

/**
 * Top-of-page tab bar shared by every /app/* route via the layout.
 * Active tab is determined by current pathname (prefix-matched for tabs
 * with subroutes like Editions). Search params are preserved on each
 * Link so the embedded-app `host` parameter flows across navigations.
 */
export function TabBar() {
  const location = useLocation();

  const isActive = (tab) => {
    if (tab.matchPrefix) return location.pathname.startsWith(tab.matchPrefix);
    return location.pathname === tab.path;
  };

  const linkTo = (pathname) => ({ pathname, search: location.search });

  return (
    <div style={{ display: "flex", gap: "10px", marginBottom: "20px", borderBottom: "2px solid #ddd", paddingBottom: "10px" }}>
      {TABS.map((tab) => (
        <Link
          key={tab.path}
          to={linkTo(tab.path)}
          style={isActive(tab) ? STYLE_ACTIVE : STYLE_BASE}
        >
          {tab.label}
        </Link>
      ))}
    </div>
  );
}
