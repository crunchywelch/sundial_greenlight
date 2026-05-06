import { json } from "@remix-run/node";
import { Form, Link, useActionData, useLoaderData, useLocation, useNavigation } from "@remix-run/react";
import { authenticate } from "../shopify.server";
import { query } from "../db.server";
import { formatVariantSku } from "../cable-config.server";
import {
  getEdition,
  updateEdition,
  EditionValidationError,
} from "../editions.server";
import { CableTable } from "../components/CableTable";

const CABLE_PREVIEW_LIMIT = 10;

export async function loader({ request, params }) {
  const { admin } = await authenticate.admin(request);
  const sku = decodeURIComponent(params.sku);
  const edition = await getEdition(sku);
  if (!edition) {
    throw new Response("Edition not found", { status: 404 });
  }

  // Cable preview: assigned-first, then by serial. Mirror the column set
  // and customer enrichment of /app/cables/{sku_group} so the embedded
  // table looks identical to the canonical view.
  const cablesResult = await query(
    `SELECT serial_number, sku_group, length, connector_code,
            shopify_gid, test_passed, test_timestamp
     FROM audio_cables
     WHERE sku_group = $1
     ORDER BY (shopify_gid IS NOT NULL AND shopify_gid != '') DESC, serial_number
     LIMIT $2`,
    [sku, CABLE_PREVIEW_LIMIT]
  );
  const cables = cablesResult.rows.map((r) => ({
    serial_number: r.serial_number,
    sku_group: r.sku_group,
    length: Number(r.length),
    connector_code: r.connector_code,
    shopify_gid: r.shopify_gid,
    test_passed: r.test_passed,
    test_timestamp: r.test_timestamp,
    variant_sku: formatVariantSku({
      group_sku: r.sku_group,
      length: Number(r.length),
      connector_code: r.connector_code,
    }),
  }));

  // Customer enrichment for assigned cables — same shape the cables-by-
  // group page uses. Single GraphQL call per unique customer.
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
  for (const cable of cables) {
    cable.customer = cable.shopify_gid ? customerMap[cable.shopify_gid] || null : null;
  }

  return json({ edition, cables, cablePreviewLimit: CABLE_PREVIEW_LIMIT });
}

export async function action({ request, params }) {
  await authenticate.admin(request);
  const sku = decodeURIComponent(params.sku);
  const form = await request.formData();
  const intent = String(form.get("intent") || "");

  const edition = await getEdition(sku);
  if (!edition) throw new Response("Edition not found", { status: 404 });

  if (intent === "save") {
    const updates = { description: String(form.get("description") || "") };
    try {
      await updateEdition(sku, updates);
    } catch (e) {
      if (e instanceof EditionValidationError) {
        return json({ error: e.message, field: e.field }, { status: 400 });
      }
      console.error("updateEdition failed:", e);
      return json({ error: `Database error: ${e.message}` }, { status: 500 });
    }
    return json({ ok: true });
  }

  if (intent === "archive" || intent === "unarchive") {
    try {
      await updateEdition(sku, { active: intent === "unarchive" });
    } catch (e) {
      console.error("updateEdition (archive toggle) failed:", e);
      return json({ error: `Database error: ${e.message}` }, { status: 500 });
    }
    return json({ ok: true });
  }

  return json({ error: `Unknown intent: ${intent}` }, { status: 400 });
}

const inputStyle = {
  width: "100%",
  padding: "10px",
  border: "1px solid #ccc",
  borderRadius: "4px",
  fontSize: "14px",
  boxSizing: "border-box",
};
const labelStyle = { display: "block", marginBottom: "5px", fontSize: "14px", fontWeight: "bold" };
const fieldStyle = { marginBottom: "16px" };

export default function EditionDetail() {
  const { edition, cables, cablePreviewLimit } = useLoaderData();
  const actionData = useActionData();
  const navigation = useNavigation();
  const location = useLocation();
  const submitting = navigation.state === "submitting";
  const editionsHref = { pathname: "/app/editions", search: location.search };
  const cablesHref = { pathname: `/app/cables/${encodeURIComponent(edition.sku)}`, search: location.search };
  const hasMoreCables = edition.cable_count > cables.length;

  return (
    <div style={{ padding: "20px", maxWidth: "1100px", margin: "0 auto", fontFamily: "system-ui, -apple-system, sans-serif" }}>
      <div style={{ marginBottom: "20px" }}>
        <Link to={editionsHref} style={{ color: "#008060", textDecoration: "none", fontSize: "14px" }}>
          ← Back to editions
        </Link>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "16px" }}>
        <div>
          <h1 style={{ fontSize: "24px", margin: "0 0 6px" }}>{edition.slug}</h1>
          <div style={{ fontSize: "14px", color: "#666" }}>
            <code>{edition.sku}</code> · {edition.series} ·{" "}
            {edition.cable_count > 0 ? (
              <Link to={cablesHref} style={{ color: "#008060", textDecoration: "none" }}>
                {edition.cable_count} cable{edition.cable_count === 1 ? "" : "s"} registered
              </Link>
            ) : (
              <>0 cables registered</>
            )}
          </div>
        </div>
        <span style={{
          padding: "4px 8px",
          borderRadius: "12px",
          fontSize: "12px",
          fontWeight: "bold",
          backgroundColor: edition.active ? "#d4edda" : "#e2e3e5",
          color: edition.active ? "#155724" : "#6c757d",
        }}>
          {edition.active ? "Active" : "Archived"}
        </span>
      </div>

      {actionData?.ok && (
        <div style={{ padding: "12px 15px", backgroundColor: "#d4edda", border: "1px solid #c3e6cb", borderRadius: "4px", marginBottom: "20px", color: "#155724" }}>
          Saved.
        </div>
      )}

      {actionData?.error && (
        <div style={{ padding: "12px 15px", backgroundColor: "#f8d7da", border: "1px solid #f5c6cb", borderRadius: "4px", marginBottom: "20px", color: "#721c24" }}>
          {actionData.error}
        </div>
      )}

      <Form method="post">
        <input type="hidden" name="intent" value="save" />

        <div style={fieldStyle}>
          <label style={labelStyle}>Description</label>
          <textarea
            name="description"
            defaultValue={edition.description || ""}
            required
            style={{ ...inputStyle, minHeight: "80px", fontFamily: "inherit" }}
          />
        </div>

        <div style={{ display: "flex", gap: "10px", marginTop: "30px" }}>
          <button
            type="submit"
            disabled={submitting}
            style={{
              padding: "10px 24px",
              backgroundColor: submitting ? "#999" : "#008060",
              color: "#fff",
              border: "none",
              borderRadius: "4px",
              fontSize: "14px",
              fontWeight: "bold",
              cursor: submitting ? "not-allowed" : "pointer",
            }}
          >
            {submitting ? "Saving…" : "Save changes"}
          </button>
        </div>
      </Form>

      {/* Cables in this edition. Same table layout as /app/cables/{sku}
          for visual consistency; canonical full list lives there. */}
      {cables.length > 0 && (
        <div style={{ marginTop: "40px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "10px" }}>
            <h2 style={{ fontSize: "16px", margin: 0 }}>Registered cables</h2>
            {hasMoreCables && (
              <Link to={cablesHref} style={{ color: "#008060", textDecoration: "none", fontSize: "13px" }}>
                View all {edition.cable_count} →
              </Link>
            )}
          </div>
          <CableTable cables={cables} />
          {hasMoreCables && (
            <div style={{ marginTop: "8px", fontSize: "12px", color: "#666" }}>
              Showing {cables.length} of {edition.cable_count}.{" "}
              <Link to={cablesHref} style={{ color: "#008060", textDecoration: "none" }}>
                See all on the cables page →
              </Link>
            </div>
          )}
        </div>
      )}

      <div style={{ marginTop: "40px", paddingTop: "20px", borderTop: "1px solid #eee" }}>
        <Form method="post">
          <button
            type="submit"
            name="intent"
            value={edition.active ? "archive" : "unarchive"}
            disabled={submitting}
            style={{
              padding: "8px 16px",
              backgroundColor: "#fff",
              color: edition.active ? "#bf5000" : "#008060",
              border: `1px solid ${edition.active ? "#bf5000" : "#008060"}`,
              borderRadius: "4px",
              fontSize: "14px",
              cursor: submitting ? "not-allowed" : "pointer",
            }}
          >
            {edition.active ? "Archive edition" : "Unarchive edition"}
          </button>
          <span style={{ marginLeft: "10px", fontSize: "13px", color: "#666" }}>
            {edition.active
              ? "Archived editions disappear from greenlight's scan picker but remain in lookups."
              : "Reactivating brings this edition back to greenlight's scan picker."}
          </span>
        </Form>
      </div>
    </div>
  );
}
