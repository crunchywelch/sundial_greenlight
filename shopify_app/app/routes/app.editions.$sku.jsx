import { json } from "@remix-run/node";
import { Form, Link, useActionData, useLoaderData, useLocation, useNavigation } from "@remix-run/react";
import { authenticate } from "../shopify.server";
import { query } from "../db.server";
import {
  getEdition,
  updateEdition,
  EditionValidationError,
} from "../editions.server";

const CABLE_PREVIEW_LIMIT = 10;

export async function loader({ request, params }) {
  await authenticate.admin(request);
  const sku = decodeURIComponent(params.sku);
  const edition = await getEdition(sku);
  if (!edition) {
    throw new Response("Edition not found", { status: 404 });
  }

  // Pull a preview of the cables in this edition. Per-cable variation
  // (length, connector) actually matters to inspect since editions can
  // span multiple sizes. Limit + "view all" link, canonical full list
  // lives at /app/cables/{sku_group}.
  const cablesResult = await query(
    `SELECT serial_number, length, connector_code, shopify_gid, test_passed, test_timestamp
     FROM audio_cables
     WHERE sku_group = $1
     ORDER BY test_timestamp DESC NULLS LAST, serial_number
     LIMIT $2`,
    [sku, CABLE_PREVIEW_LIMIT]
  );
  const cables = cablesResult.rows.map((r) => ({
    serial_number: r.serial_number,
    length: Number(r.length),
    connector_code: r.connector_code,
    assigned: !!(r.shopify_gid && r.shopify_gid !== ""),
    test_passed: r.test_passed,
    tested: r.test_passed !== null,
  }));

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
    <div style={{ padding: "20px", maxWidth: "720px", margin: "0 auto", fontFamily: "system-ui, -apple-system, sans-serif" }}>
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

      {/* Cables in this edition. Compact preview; full list at /app/cables/{sku}. */}
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
          <div style={{ border: "1px solid #eee", borderRadius: "4px", overflow: "hidden" }}>
            {cables.map((cable, i) => (
              <div
                key={cable.serial_number}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "12px",
                  padding: "10px 12px",
                  borderBottom: i < cables.length - 1 ? "1px solid #eee" : "none",
                  fontSize: "13px",
                }}
              >
                <span style={{ fontWeight: "bold", flex: "0 0 auto" }}>#{cable.serial_number}</span>
                <span style={{ color: "#666", flex: "1 1 auto" }}>
                  {cable.length}ft{cable.connector_code === "-R" ? ", right angle" : ""}
                </span>
                {cable.tested && (
                  <span style={{
                    padding: "2px 6px",
                    borderRadius: "10px",
                    fontSize: "11px",
                    fontWeight: "bold",
                    backgroundColor: cable.test_passed ? "#d4edda" : "#f8d7da",
                    color: cable.test_passed ? "#155724" : "#721c24",
                  }}>
                    {cable.test_passed ? "Pass" : "Fail"}
                  </span>
                )}
                <span style={{
                  padding: "2px 6px",
                  borderRadius: "10px",
                  fontSize: "11px",
                  fontWeight: "bold",
                  backgroundColor: cable.assigned ? "#e8f5ff" : "#fff3cd",
                  color: cable.assigned ? "#0050b3" : "#856404",
                }}>
                  {cable.assigned ? "Assigned" : "Available"}
                </span>
              </div>
            ))}
          </div>
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
