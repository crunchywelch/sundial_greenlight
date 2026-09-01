import { json } from "@remix-run/node";
import { useLoaderData, Link, useLocation } from "@remix-run/react";
import { authenticate } from "../shopify.server";
import { query } from "../db.server";
import { parseGroupSku, formatVariantSku, seriesForPrefix, seriesDataForPrefix } from "../cable-config.server";
import { cableState, STATE_META } from "../components/CableTable";
import { CableLookup } from "../components/CableLookup";

const numericId = (gid) => (gid ? String(gid).split("/").pop() : null);

export async function loader({ request, params }) {
  const { admin } = await authenticate.admin(request);
  const serial = decodeURIComponent(params.serial);

  const res = await query(
    `SELECT ac.serial_number, ac.sku_group, ac.prefix, ac.length, ac.connector_code,
            ac.connector_finish, ac.test_passed, ac.resistance_adc, ac.calibration_adc,
            ac.operator, ac.notes, ac.test_timestamp, ac.updated_timestamp,
            ac.shopify_gid, ac.shopify_order_gid, ac.registration_code, ac.registered_at,
            ac.wholesale_company_gid, ac.wholesale_location_gid,
            sg.description
     FROM audio_cables ac
     LEFT JOIN sku_group sg ON sg.sku = ac.sku_group
     WHERE ac.serial_number = $1`,
    [serial]
  );

  if (res.rows.length === 0) {
    return json({ serial, cable: null, events: [] });
  }

  const row = res.rows[0];
  const parsed = parseGroupSku(row.sku_group);
  const seriesData = seriesDataForPrefix(row.prefix);
  const connectorDisplay =
    seriesData?.connectors?.find((c) => (c.code ?? "") === (row.connector_code ?? ""))?.display ?? null;

  // Resolve the Shopify objects this cable references in a single nodes() call.
  const ids = [row.shopify_gid, row.wholesale_company_gid, row.wholesale_location_gid, row.shopify_order_gid].filter(Boolean);
  const nodeMap = {};
  if (ids.length > 0) {
    try {
      const resp = await admin.graphql(
        `#graphql
        query resolve($ids: [ID!]!) {
          nodes(ids: $ids) {
            __typename
            ... on Customer { id firstName lastName email phone }
            ... on Company { id name }
            ... on CompanyLocation { id name }
            ... on Order { id name }
          }
        }`,
        { variables: { ids } }
      );
      const data = await resp.json();
      for (const node of data.data?.nodes ?? []) {
        if (node?.id) nodeMap[node.id] = node;
      }
    } catch (error) {
      console.error("Error resolving cable references:", error);
    }
  }

  const evRes = await query(
    `SELECT event, actor, detail, created_at
     FROM cable_events WHERE serial_number = $1
     ORDER BY id DESC LIMIT 50`,
    [serial]
  );

  const cable = {
    serial_number: row.serial_number,
    sku_group: row.sku_group,
    variant_sku: formatVariantSku({
      prefix: row.prefix,
      group_sku: row.sku_group,
      length: Number(row.length),
      connector_code: row.connector_code,
    }),
    series: seriesForPrefix(row.prefix),
    length: Number(row.length),
    connector_type: connectorDisplay,
    connector_finish: row.connector_finish,
    description: row.description,
    edition_slug: parsed.kind === "ltd" ? parsed.slug : null,
    test_passed: row.test_passed,
    resistance_adc: row.resistance_adc,
    calibration_adc: row.calibration_adc,
    operator: row.operator,
    notes: row.notes,
    test_timestamp: row.test_timestamp,
    updated_timestamp: row.updated_timestamp,
    shopify_gid: row.shopify_gid,
    shopify_order_gid: row.shopify_order_gid,
    registration_code: row.registration_code,
    registered_at: row.registered_at,
    wholesale_company_gid: row.wholesale_company_gid,
    wholesale_location_gid: row.wholesale_location_gid,
    customer: row.shopify_gid ? nodeMap[row.shopify_gid] || null : null,
    company: row.wholesale_company_gid ? nodeMap[row.wholesale_company_gid] || null : null,
    location: row.wholesale_location_gid ? nodeMap[row.wholesale_location_gid] || null : null,
    order: row.shopify_order_gid ? nodeMap[row.shopify_order_gid] || null : null,
  };

  return json({ serial, cable, events: evRes.rows });
}

const fmtDate = (v) => (v ? new Date(v).toLocaleString() : "—");
const card = { border: "1px solid #ddd", borderRadius: "8px", padding: "16px", backgroundColor: "#fff" };
const label = { fontSize: "12px", color: "#888", textTransform: "uppercase", letterSpacing: "0.03em" };
const val = { fontSize: "14px", color: "#222" };

function Field({ k, children }) {
  return (
    <div style={{ marginBottom: "10px" }}>
      <div style={label}>{k}</div>
      <div style={val}>{children ?? "—"}</div>
    </div>
  );
}

export default function CableDetail() {
  const { serial, cable, events } = useLoaderData();
  const location = useLocation();

  if (!cable) {
    return (
      <div style={{ padding: "20px", maxWidth: "1100px", margin: "0 auto", fontFamily: "system-ui, -apple-system, sans-serif" }}>
        <CableLookup defaultValue={serial} />
        <div style={{ padding: "40px", textAlign: "center", backgroundColor: "#f5f5f5", borderRadius: "8px", color: "#666" }}>
          No cable found with serial <strong>{serial}</strong>.
        </div>
      </div>
    );
  }

  const state = cableState(cable);
  const meta = STATE_META[state];
  const groupHref = { pathname: `/app/cables/${encodeURIComponent(cable.sku_group)}`, search: location.search };
  const editionHref = cable.edition_slug ? { pathname: `/app/editions/${encodeURIComponent(cable.sku_group)}`, search: location.search } : null;

  return (
    <div style={{ padding: "20px", maxWidth: "1100px", margin: "0 auto", fontFamily: "system-ui, -apple-system, sans-serif" }}>
      <CableLookup defaultValue={cable.serial_number} />

      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "16px" }}>
        <div>
          <h1 style={{ fontSize: "26px", margin: "0 0 4px" }}>#{cable.serial_number}</h1>
          <div style={{ fontSize: "14px", color: "#666" }}>
            <Link to={groupHref} style={{ color: "#008060", textDecoration: "none" }}><code>{cable.variant_sku}</code></Link>
            {cable.series ? ` · ${cable.series}` : ""}
            {cable.edition_slug ? ` · Limited Edition ${cable.edition_slug}` : ""}
          </div>
        </div>
        <span style={{ padding: "6px 12px", borderRadius: "14px", fontSize: "13px", fontWeight: "bold", backgroundColor: meta.bg, color: meta.fg }}>
          {meta.label}
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "16px" }}>
        {/* Identity */}
        <div style={card}>
          <h2 style={{ fontSize: "15px", margin: "0 0 12px" }}>Identity</h2>
          <Field k="Variant SKU">{cable.variant_sku}</Field>
          <Field k="Series">{cable.series}</Field>
          <Field k="Length">{cable.length != null ? `${cable.length} ft` : null}</Field>
          <Field k="Connector">{cable.connector_type}{cable.connector_finish ? ` · ${cable.connector_finish}` : ""}</Field>
          <Field k="Description">{cable.description}</Field>
        </div>

        {/* QC */}
        <div style={card}>
          <h2 style={{ fontSize: "15px", margin: "0 0 12px" }}>Quality control</h2>
          <Field k="Result">
            {cable.test_passed === true ? <span style={{ color: "#155724", fontWeight: "bold" }}>Passed</span>
              : cable.test_passed === false ? <span style={{ color: "#721c24", fontWeight: "bold" }}>Failed</span>
              : <span style={{ color: "#856404", fontWeight: "bold" }}>Not tested</span>}
          </Field>
          <Field k="Resistance / calibration">{cable.resistance_adc != null ? `${cable.resistance_adc} / ${cable.calibration_adc ?? "—"}` : null}</Field>
          <Field k="Tested">{cable.test_timestamp ? fmtDate(cable.test_timestamp) : null}</Field>
          <Field k="Operator">{cable.operator}</Field>
          <Field k="Notes">{cable.notes}</Field>
        </div>
      </div>

      {/* Commercial */}
      <div style={{ ...card, marginBottom: "16px" }}>
        <h2 style={{ fontSize: "15px", margin: "0 0 12px" }}>Commercial</h2>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
          <Field k="End owner">
            {cable.customer ? (
              <a href={`shopify:admin/customers/${numericId(cable.shopify_gid)}`} target="_top" style={{ color: "#008060", textDecoration: "none" }}>
                {`${cable.customer.firstName ?? ""} ${cable.customer.lastName ?? ""}`.trim() || cable.customer.email || "Customer"}
              </a>
            ) : <span style={{ color: "#888" }}>Not registered to an owner</span>}
          </Field>
          <Field k="Sold via (dealer)">
            {cable.company ? (
              <a href={`shopify:admin/companies/${numericId(cable.wholesale_company_gid)}`} target="_top" style={{ color: "#008060", textDecoration: "none" }}>
                {cable.company.name}{cable.location ? ` — ${cable.location.name}` : ""}
              </a>
            ) : <span style={{ color: "#888" }}>Not sold to a dealer</span>}
          </Field>
          <Field k="Order">
            {cable.order ? (
              <a href={`shopify:admin/orders/${numericId(cable.shopify_order_gid)}`} target="_top" style={{ color: "#008060", textDecoration: "none" }}>
                {cable.order.name}
              </a>
            ) : null}
          </Field>
          <Field k="Registration code">{cable.registration_code ? <code>{cable.registration_code}</code> : <span style={{ color: "#888" }}>None</span>}</Field>
          <Field k="Registered by buyer">{cable.registered_at ? fmtDate(cable.registered_at) : <span style={{ color: "#888" }}>Not yet</span>}</Field>
          {editionHref && <Field k="Edition"><Link to={editionHref} style={{ color: "#008060", textDecoration: "none" }}>Edit edition</Link></Field>}
        </div>
      </div>

      {/* History */}
      <div style={card}>
        <h2 style={{ fontSize: "15px", margin: "0 0 12px" }}>History</h2>
        {events.length === 0 ? (
          <div style={{ fontSize: "13px", color: "#888" }}>No recorded events.</div>
        ) : (
          <div>
            {events.map((e, i) => (
              <div key={i} style={{ display: "flex", gap: "12px", padding: "8px 0", borderBottom: i < events.length - 1 ? "1px solid #f0f0f0" : "none", fontSize: "13px" }}>
                <div style={{ color: "#888", whiteSpace: "nowrap", minWidth: "150px" }}>{fmtDate(e.created_at)}</div>
                <div style={{ fontWeight: "bold", minWidth: "150px" }}>{e.event}</div>
                <div style={{ color: "#666" }}>{e.actor}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
