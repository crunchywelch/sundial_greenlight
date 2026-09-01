import crypto from "node:crypto";
import { json } from "@remix-run/node";
import { useEffect, useState } from "react";
import { useLoaderData, Link, useLocation, useFetcher } from "@remix-run/react";
import { authenticate } from "../shopify.server";
import { query, getClient, recordCableEvent } from "../db.server";
import { parseGroupSku, formatVariantSku, seriesForPrefix, seriesDataForPrefix } from "../cable-config.server";
import { cableState, STATE_META } from "../components/CableTable";
import { CableLookup } from "../components/CableLookup";

const numericId = (gid) => (gid ? String(gid).split("/").pop() : null);

// Mirror of greenlight/registration.py generate_registration_code: a
// crypto-random XXXX-XXXX over an unambiguous alphabet.
const CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ";
function generateRegistrationCode() {
  let s = "";
  for (let i = 0; i < 8; i++) s += CODE_ALPHABET[crypto.randomInt(CODE_ALPHABET.length)];
  return `${s.slice(0, 4)}-${s.slice(4)}`;
}

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

// All mutations for one cable live here. They mirror the greenlight db.py
// reference (assign_cable_to_customer, unassign_cable, batch_assign_registration_codes,
// clear_registration_code): the same guards, and every write is paired with a
// cable_event on the same transaction. Actor is "admin".
export async function action({ request, params }) {
  const { admin } = await authenticate.admin(request);
  const serial = decodeURIComponent(params.serial);
  const form = await request.formData();
  const intent = form.get("intent");

  // Read-only: search Shopify customers for the assign picker.
  if (intent === "searchCustomer") {
    const term = (form.get("searchTerm") || "").toString().trim();
    if (!term) return json({ customers: [] });
    try {
      const resp = await admin.graphql(
        `#graphql
        query searchCustomers($query: String!) {
          customers(first: 10, query: $query) {
            edges { node { id firstName lastName email phone } }
          }
        }`,
        { variables: { query: term } }
      );
      const data = await resp.json();
      if (data.errors) return json({ error: "Customer search failed" }, { status: 500 });
      return json({ customers: (data.data?.customers?.edges || []).map((e) => e.node) });
    } catch (err) {
      return json({ error: "Customer search failed" }, { status: 500 });
    }
  }

  if (intent === "assignCustomer") {
    const customerId = (form.get("customerId") || "").toString();
    if (!customerId) return json({ error: "No customer selected" }, { status: 400 });

    const cur = await query(
      `SELECT shopify_gid, wholesale_company_gid, test_passed FROM audio_cables WHERE serial_number = $1`,
      [serial]
    );
    if (cur.rows.length === 0) return json({ error: "Cable not found" }, { status: 404 });
    const c = cur.rows[0];
    if (c.shopify_gid && c.shopify_gid !== "") {
      return json({ error: "Cable is already registered to an owner. Release it first.", code: "ALREADY_ASSIGNED" }, { status: 409 });
    }
    if (c.wholesale_company_gid && c.wholesale_company_gid !== "") {
      return json({ error: "Cable is sold to a dealer and cannot be assigned to a retail customer.", code: "SOLD_TO_DEALER" }, { status: 409 });
    }
    if (c.test_passed !== true) {
      return json(
        c.test_passed === false
          ? { error: "Cable failed QC and cannot be assigned.", code: "QC_FAILED" }
          : { error: "Cable has not passed QC yet and cannot be assigned.", code: "NOT_TESTED" },
        { status: 409 }
      );
    }

    const client = await getClient();
    try {
      await client.query("BEGIN");
      await client.query(
        `UPDATE audio_cables SET shopify_gid = $1, updated_timestamp = NOW() WHERE serial_number = $2`,
        [customerId, serial]
      );
      await recordCableEvent(client, {
        serialNumber: serial,
        event: "assigned_customer",
        actor: "admin",
        detail: { from: null, to: customerId },
      });
      await client.query("COMMIT");
    } catch (err) {
      await client.query("ROLLBACK");
      throw err;
    } finally {
      client.release();
    }
    return json({ ok: true, message: "Cable registered to the customer." });
  }

  if (intent === "unassignCustomer" || intent === "unassignDealer") {
    const channel = intent === "unassignCustomer" ? "retail" : "wholesale";
    const cur = await query(
      `SELECT shopify_gid, wholesale_company_gid FROM audio_cables WHERE serial_number = $1`,
      [serial]
    );
    if (cur.rows.length === 0) return json({ error: "Cable not found" }, { status: 404 });
    const { shopify_gid, wholesale_company_gid } = cur.rows[0];

    if (channel === "retail" && !shopify_gid) {
      return json({ error: "Cable has no registered owner to release." }, { status: 409 });
    }
    if (channel === "wholesale" && !wholesale_company_gid) {
      return json({ error: "Cable is not sold to a dealer." }, { status: 409 });
    }

    const client = await getClient();
    try {
      await client.query("BEGIN");
      if (channel === "retail") {
        // Clear the owner and their registration. The order gid belongs to
        // whichever channel bought the cable, so only drop it when there's no
        // dealer (mirrors greenlight unassign_cable).
        await client.query(
          `UPDATE audio_cables
           SET shopify_gid = NULL, registered_at = NULL,
               shopify_order_gid = CASE WHEN wholesale_company_gid IS NULL THEN NULL ELSE shopify_order_gid END,
               updated_timestamp = NOW()
           WHERE serial_number = $1`,
          [serial]
        );
        await recordCableEvent(client, {
          serialNumber: serial,
          event: "unassigned_customer",
          actor: "admin",
          detail: { from: shopify_gid, to: null },
        });
      } else {
        await client.query(
          `UPDATE audio_cables
           SET wholesale_company_gid = NULL, wholesale_location_gid = NULL,
               shopify_order_gid = NULL, updated_timestamp = NOW()
           WHERE serial_number = $1`,
          [serial]
        );
        await recordCableEvent(client, {
          serialNumber: serial,
          event: "unassigned_dealer",
          actor: "admin",
          detail: { from: wholesale_company_gid, to: null },
        });
      }
      await client.query("COMMIT");
    } catch (err) {
      await client.query("ROLLBACK");
      throw err;
    } finally {
      client.release();
    }
    return json({ ok: true, message: channel === "retail" ? "Released the registered owner." : "Released the dealer." });
  }

  if (intent === "genCode") {
    // A code is an attribute, not a stock state — it never moves a cable out of
    // inventory. Retry on the (rare) unique collision. WHERE registration_code
    // IS NULL makes this a no-op if a code already exists.
    const client = await getClient();
    try {
      let assigned = null;
      for (let attempt = 0; attempt < 3 && !assigned; attempt++) {
        const code = generateRegistrationCode();
        try {
          await client.query("BEGIN");
          const r = await client.query(
            `UPDATE audio_cables SET registration_code = $1, updated_timestamp = NOW()
             WHERE serial_number = $2 AND registration_code IS NULL
             RETURNING registration_code`,
            [code, serial]
          );
          if (r.rows.length === 0) {
            await client.query("ROLLBACK");
            const ex = await query(`SELECT registration_code FROM audio_cables WHERE serial_number = $1`, [serial]);
            if (ex.rows.length === 0) return json({ error: "Cable not found" }, { status: 404 });
            return json({ error: `Cable already has a code: ${ex.rows[0].registration_code}` }, { status: 409 });
          }
          await recordCableEvent(client, {
            serialNumber: serial,
            event: "code_generated",
            actor: "admin",
            detail: { to: code },
          });
          await client.query("COMMIT");
          assigned = code;
        } catch (err) {
          await client.query("ROLLBACK");
          if (/(unique|duplicate)/i.test(String(err.message))) continue;
          throw err;
        }
      }
      if (!assigned) return json({ error: "Could not generate a unique code, try again." }, { status: 500 });
      return json({ ok: true, message: `Registration code generated: ${assigned}` });
    } finally {
      client.release();
    }
  }

  if (intent === "clearCode") {
    const client = await getClient();
    try {
      await client.query("BEGIN");
      const r = await client.query(
        `UPDATE audio_cables SET registration_code = NULL, updated_timestamp = NOW()
         WHERE serial_number = $1 AND registration_code IS NOT NULL
         RETURNING serial_number`,
        [serial]
      );
      if (r.rows.length === 0) {
        await client.query("ROLLBACK");
        return json({ error: "Cable has no registration code to clear." }, { status: 409 });
      }
      await recordCableEvent(client, {
        serialNumber: serial,
        event: "code_cleared",
        actor: "admin",
        detail: null,
      });
      await client.query("COMMIT");
    } catch (err) {
      await client.query("ROLLBACK");
      throw err;
    } finally {
      client.release();
    }
    return json({ ok: true, message: "Registration code cleared." });
  }

  return json({ error: "Unknown action" }, { status: 400 });
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

const btn = (color, disabled) => ({
  padding: "8px 16px",
  backgroundColor: disabled ? "#ccc" : color,
  color: "#fff",
  border: "none",
  borderRadius: "4px",
  cursor: disabled ? "not-allowed" : "pointer",
  fontSize: "14px",
  fontWeight: "bold",
});

function ManageCable({ cable }) {
  const action = useFetcher();
  const search = useFetcher();
  const [selected, setSelected] = useState(null);
  const [term, setTerm] = useState("");

  const busy = action.state !== "idle";
  const owned = !!cable.shopify_gid;
  const dealt = !!cable.wholesale_company_gid;
  const passed = cable.test_passed === true;
  const results = search.data?.customers || [];

  // After a successful mutation the loader revalidates and the cards update;
  // clear the local picker state so it doesn't linger.
  useEffect(() => {
    if (action.data?.ok) {
      setSelected(null);
      setTerm("");
    }
  }, [action.data]);

  const submit = (fields) => {
    const fd = new FormData();
    Object.entries(fields).forEach(([k, v]) => fd.append(k, v));
    action.submit(fd, { method: "post" });
  };

  const doSearch = (e) => {
    e.preventDefault();
    const fd = new FormData();
    fd.append("intent", "searchCustomer");
    fd.append("searchTerm", term);
    search.submit(fd, { method: "post" });
  };

  return (
    <div style={{ ...card, marginBottom: "16px" }}>
      <h2 style={{ fontSize: "15px", margin: "0 0 12px" }}>Manage</h2>

      {action.data?.message && (
        <div style={{ padding: "10px 12px", backgroundColor: "#d4edda", border: "1px solid #c3e6cb", borderRadius: "4px", marginBottom: "12px", color: "#155724", fontSize: "13px" }}>
          {action.data.message}
        </div>
      )}
      {action.data?.error && (
        <div style={{ padding: "10px 12px", backgroundColor: "#f8d7da", border: "1px solid #f5c6cb", borderRadius: "4px", marginBottom: "12px", color: "#721c24", fontSize: "13px" }}>
          {action.data.error}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px" }}>
        {/* Ownership / dealer */}
        <div>
          <div style={{ ...label, marginBottom: "8px" }}>Ownership</div>

          {dealt && (
            <div style={{ marginBottom: "12px" }}>
              <div style={{ fontSize: "13px", color: "#5c3d99", marginBottom: "6px" }}>Sold to a dealer.</div>
              <button disabled={busy} onClick={() => submit({ intent: "unassignDealer" })} style={btn("#5c3d99", busy)}>
                Release dealer
              </button>
            </div>
          )}

          {owned && (
            <div style={{ marginBottom: "12px" }}>
              <div style={{ fontSize: "13px", color: "#1a3d7c", marginBottom: "6px" }}>Registered to an end owner.</div>
              <button disabled={busy} onClick={() => submit({ intent: "unassignCustomer" })} style={btn("#1a3d7c", busy)}>
                Release owner
              </button>
            </div>
          )}

          {!owned && !dealt && !passed && (
            <div style={{ fontSize: "13px", color: "#856404" }}>
              Assign after the cable passes QC (tested in Greenlight).
            </div>
          )}

          {!owned && !dealt && passed && (
            <div>
              <div style={{ fontSize: "13px", color: "#666", marginBottom: "8px" }}>Register this cable to a retail customer.</div>
              <form onSubmit={doSearch} style={{ display: "flex", gap: "8px", marginBottom: "10px" }}>
                <input
                  type="text"
                  value={term}
                  onChange={(e) => setTerm(e.target.value)}
                  placeholder="Search name, email, phone"
                  style={{ flex: 1, padding: "8px", border: "1px solid #ccc", borderRadius: "4px", fontSize: "13px" }}
                />
                <button type="submit" disabled={search.state !== "idle"} style={btn("#008060", search.state !== "idle")}>Search</button>
              </form>

              {selected && (
                <div style={{ padding: "10px", backgroundColor: "#e8f5ff", border: "1px solid #b3d9ff", borderRadius: "4px", marginBottom: "10px", fontSize: "13px" }}>
                  <div>{`${selected.firstName ?? ""} ${selected.lastName ?? ""}`.trim() || selected.email}</div>
                  <button disabled={busy} onClick={() => submit({ intent: "assignCustomer", customerId: selected.id })} style={{ ...btn("#008060", busy), marginTop: "8px" }}>
                    Register to this customer
                  </button>
                </div>
              )}

              {results.map((n) => (
                <div
                  key={n.id}
                  onClick={() => setSelected(n)}
                  style={{ padding: "10px", border: "1px solid #ddd", borderRadius: "4px", marginBottom: "6px", cursor: "pointer", fontSize: "13px", backgroundColor: selected?.id === n.id ? "#f0f9ff" : "#fff" }}
                >
                  <div style={{ fontWeight: "bold" }}>{`${n.firstName ?? ""} ${n.lastName ?? ""}`.trim() || "(no name)"}</div>
                  {n.email && <div style={{ color: "#666" }}>{n.email}</div>}
                </div>
              ))}
              {search.data && results.length === 0 && (
                <div style={{ fontSize: "13px", color: "#888" }}>No customers found.</div>
              )}
            </div>
          )}
        </div>

        {/* Registration code */}
        <div>
          <div style={{ ...label, marginBottom: "8px" }}>Registration code</div>
          {cable.registration_code ? (
            <div>
              <div style={{ fontSize: "14px", marginBottom: "8px" }}><code>{cable.registration_code}</code></div>
              <button disabled={busy} onClick={() => submit({ intent: "clearCode" })} style={btn("#b02a37", busy)}>
                Clear code
              </button>
              <div style={{ fontSize: "12px", color: "#888", marginTop: "6px" }}>
                Clearing invalidates any label already printed with this code.
              </div>
            </div>
          ) : (
            <div>
              <div style={{ fontSize: "13px", color: "#666", marginBottom: "8px" }}>No code yet.</div>
              <button disabled={busy} onClick={() => submit({ intent: "genCode" })} style={btn("#008060", busy)}>
                Generate code
              </button>
            </div>
          )}
        </div>
      </div>
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

      {/* Manage */}
      <ManageCable cable={cable} />

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
