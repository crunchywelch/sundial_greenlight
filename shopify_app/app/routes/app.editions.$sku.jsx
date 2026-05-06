import { json } from "@remix-run/node";
import { Form, Link, useActionData, useLoaderData, useLocation, useNavigation } from "@remix-run/react";
import { authenticate } from "../shopify.server";
import {
  getEdition,
  updateEdition,
  EditionValidationError,
} from "../editions.server";

export async function loader({ request, params }) {
  await authenticate.admin(request);
  const sku = decodeURIComponent(params.sku);
  const edition = await getEdition(sku);
  if (!edition) {
    throw new Response("Edition not found", { status: 404 });
  }
  return json({ edition });
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
const lockedStyle = { ...inputStyle, backgroundColor: "#f5f5f5", color: "#666" };
const labelStyle = { display: "block", marginBottom: "5px", fontSize: "14px", fontWeight: "bold" };
const fieldStyle = { marginBottom: "16px" };
const helpStyle = { fontSize: "12px", color: "#666", marginTop: "4px" };

export default function EditionDetail() {
  const { edition } = useLoaderData();
  const actionData = useActionData();
  const navigation = useNavigation();
  const location = useLocation();
  const submitting = navigation.state === "submitting";
  const locked = edition.cable_count > 0;
  const editionsHref = { pathname: "/app/editions", search: location.search };

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
            <code>{edition.sku}</code> · {edition.series} · {edition.cable_count} cable{edition.cable_count === 1 ? "" : "s"} registered
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
          <label style={labelStyle}>
            Description {locked && <span style={{ color: "#bf5000", fontWeight: "normal" }}>(locked)</span>}
          </label>
          {locked ? (
            <textarea name="description" defaultValue={edition.description || ""} readOnly style={{ ...lockedStyle, minHeight: "80px", fontFamily: "inherit" }} />
          ) : (
            <textarea name="description" defaultValue={edition.description || ""} required style={{ ...inputStyle, minHeight: "80px", fontFamily: "inherit" }} />
          )}
          {locked && <div style={helpStyle}>Cannot edit — cables already registered against this edition.</div>}
        </div>

        <div style={{ display: "flex", gap: "10px", marginTop: "30px" }}>
          <button
            type="submit"
            disabled={submitting || locked}
            style={{
              padding: "10px 24px",
              backgroundColor: submitting || locked ? "#999" : "#008060",
              color: "#fff",
              border: "none",
              borderRadius: "4px",
              fontSize: "14px",
              fontWeight: "bold",
              cursor: submitting || locked ? "not-allowed" : "pointer",
            }}
          >
            {submitting ? "Saving…" : "Save changes"}
          </button>
        </div>
      </Form>

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
