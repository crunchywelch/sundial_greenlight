import { useMemo, useState } from "react";
import { json } from "@remix-run/node";
import { useLoaderData } from "@remix-run/react";
import { authenticate } from "../shopify.server";
import { query } from "../db.server";
import { parseGroupSku, formatVariantSku } from "../cable-config.server";
import { CableTable, cableState, STATE_META } from "../components/CableTable";

export async function loader({ request, params }) {
  const { admin } = await authenticate.admin(request);
  const skuGroup = decodeURIComponent(params.sku);
  const url = new URL(request.url);
  const initialState = url.searchParams.get("state") || "all";

  // Per-state counts for the header (each cable counted once; sum to total).
  // Priority matches the inventory hub: assigned > wholesale > QC outcome.
  const countResult = await query(
    `SELECT
      COUNT(*) AS total,
      COUNT(*) FILTER (WHERE shopify_gid IS NOT NULL AND shopify_gid != '') AS assigned,
      COUNT(*) FILTER (WHERE (shopify_gid IS NULL OR shopify_gid = '') AND registration_code IS NOT NULL) AS wholesale,
      COUNT(*) FILTER (WHERE (shopify_gid IS NULL OR shopify_gid = '') AND registration_code IS NULL AND test_passed = TRUE) AS retail,
      COUNT(*) FILTER (WHERE (shopify_gid IS NULL OR shopify_gid = '') AND registration_code IS NULL AND test_passed = FALSE) AS failed,
      COUNT(*) FILTER (WHERE (shopify_gid IS NULL OR shopify_gid = '') AND registration_code IS NULL AND test_passed IS NULL) AS untested
    FROM audio_cables
    WHERE sku_group = $1`,
    [skuGroup]
  );
  const counts = countResult.rows[0];

  // Every cable in this group — all states alike. This doubles as the
  // canonical "show me everything in SC-LTD-PHISH26" view and the historical
  // "who has cables in this group" view.
  const result = await query(
    `SELECT
      ac.serial_number,
      ac.sku_group,
      ac.prefix,
      ac.length,
      ac.connector_code,
      ac.shopify_gid,
      ac.registration_code,
      ac.test_timestamp,
      ac.test_passed
    FROM audio_cables ac
    WHERE ac.sku_group = $1
    ORDER BY (ac.shopify_gid IS NOT NULL AND ac.shopify_gid != '') DESC, ac.serial_number`,
    [skuGroup]
  );

  const parsed = parseGroupSku(skuGroup);
  const cables = result.rows.map((row) => ({
    ...row,
    length: Number(row.length),
    variant_sku: formatVariantSku({
      prefix: row.prefix,
      group_sku: row.sku_group,
      length: Number(row.length),
      connector_code: row.connector_code,
    }),
  }));

  // Customer enrichment
  const customerIds = [...new Set(cables.filter((c) => c.shopify_gid).map((c) => c.shopify_gid))];
  const customerMap = {};
  for (const customerId of customerIds) {
    try {
      const response = await admin.graphql(
        `#graphql
        query getCustomer($id: ID!) {
          customer(id: $id) { id firstName lastName email }
        }`,
        { variables: { id: customerId } }
      );
      const data = await response.json();
      if (data.data?.customer) customerMap[customerId] = data.data.customer;
    } catch (error) {
      console.error(`Error fetching customer ${customerId}:`, error);
    }
  }

  let groupSubtitle = null;
  if (parsed.kind === "catalog") groupSubtitle = parsed.pattern_name || null;
  else if (parsed.kind === "ltd") groupSubtitle = `Limited Edition · ${parsed.slug}`;
  else if (parsed.kind === "misc") groupSubtitle = parsed.series || null;

  const cablesWithCustomers = cables.map((cable) => ({
    ...cable,
    customer: cable.shopify_gid ? customerMap[cable.shopify_gid] || null : null,
  }));

  return json({
    sku_group: skuGroup,
    cables: cablesWithCustomers,
    groupSubtitle,
    initialState,
    counts: {
      total: parseInt(counts.total),
      retail: parseInt(counts.retail),
      wholesale: parseInt(counts.wholesale),
      assigned: parseInt(counts.assigned),
      failed: parseInt(counts.failed),
      untested: parseInt(counts.untested),
    },
  });
}

const STATE_ORDER = ["retail", "wholesale", "assigned", "failed", "untested"];

export default function CablesBySkuGroup() {
  const { sku_group, cables, groupSubtitle, counts, initialState } = useLoaderData();
  const [serialFilter, setSerialFilter] = useState("");
  const [stateFilter, setStateFilter] = useState(
    STATE_ORDER.includes(initialState) ? initialState : "all"
  );

  const serialLower = serialFilter.trim().toLowerCase();
  const filteredCables = useMemo(
    () =>
      cables.filter(
        (c) =>
          (stateFilter === "all" || cableState(c) === stateFilter) &&
          (!serialLower || c.serial_number.toLowerCase().includes(serialLower))
      ),
    [cables, stateFilter, serialLower]
  );

  return (
    <div style={{ padding: "20px", maxWidth: "1200px", margin: "0 auto", fontFamily: "system-ui, -apple-system, sans-serif" }}>
      <div style={{ marginBottom: "20px" }}>
        <button
          onClick={() => window.history.back()}
          style={{ color: "#008060", textDecoration: "none", fontSize: "14px", background: "none", border: "none", cursor: "pointer", padding: 0 }}
        >
          ← Back
        </button>
      </div>

      <div style={{ marginBottom: "24px" }}>
        <h1 style={{ fontSize: "24px", marginBottom: "10px" }}>{sku_group}</h1>
        {groupSubtitle && <div style={{ fontSize: "14px", color: "#666", marginBottom: "12px" }}>{groupSubtitle}</div>}

        {/* State chips double as one-click filters. */}
        <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", alignItems: "center" }}>
          <Chip active={stateFilter === "all"} onClick={() => setStateFilter("all")} label="Total" value={counts.total} bg="#eee" fg="#333" />
          {STATE_ORDER.map((s) => (
            <Chip
              key={s}
              active={stateFilter === s}
              onClick={() => setStateFilter(stateFilter === s ? "all" : s)}
              label={STATE_META[s].label}
              value={counts[s]}
              bg={STATE_META[s].bg}
              fg={STATE_META[s].fg}
            />
          ))}
        </div>
      </div>

      <div style={{ display: "flex", gap: "10px", alignItems: "center", marginBottom: "12px", flexWrap: "wrap" }}>
        <input
          type="text"
          value={serialFilter}
          onChange={(e) => setSerialFilter(e.target.value)}
          placeholder="Filter by serial number…"
          style={{ flex: "1 1 220px", padding: "8px 10px", border: "1px solid #ccc", borderRadius: "4px", fontSize: "14px" }}
        />
        {(serialFilter || stateFilter !== "all") && (
          <button
            onClick={() => { setSerialFilter(""); setStateFilter("all"); }}
            style={{ padding: "8px 12px", backgroundColor: "#fff", border: "1px solid #ddd", borderRadius: "4px", fontSize: "14px", cursor: "pointer" }}
          >
            Clear
          </button>
        )}
        <span style={{ fontSize: "13px", color: "#666", whiteSpace: "nowrap" }}>
          {serialLower || stateFilter !== "all" ? `${filteredCables.length} of ${cables.length}` : `${cables.length} cables`}
        </span>
      </div>

      {cables.length === 0 ? (
        <div style={{ padding: "40px", textAlign: "center", backgroundColor: "#f5f5f5", borderRadius: "8px", color: "#666" }}>
          No cables registered in this group.
        </div>
      ) : filteredCables.length === 0 ? (
        <div style={{ padding: "40px", textAlign: "center", backgroundColor: "#f5f5f5", borderRadius: "8px", color: "#666" }}>
          No cables match the current filters.
        </div>
      ) : (
        <CableTable cables={filteredCables} />
      )}
    </div>
  );
}

function Chip({ active, onClick, label, value, bg, fg }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "6px",
        padding: "6px 12px",
        borderRadius: "16px",
        border: active ? `2px solid ${fg}` : "2px solid transparent",
        backgroundColor: bg,
        color: fg,
        cursor: "pointer",
        fontSize: "13px",
        fontWeight: "bold",
      }}
    >
      <span>{label}</span>
      <span style={{ fontSize: "15px" }}>{value}</span>
    </button>
  );
}
