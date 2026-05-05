import { useState } from "react";
import { json, redirect } from "@remix-run/node";
import { Form, Link, useActionData, useLoaderData, useLocation, useNavigation } from "@remix-run/react";
import { authenticate } from "../shopify.server";
import {
  createLtdEdition,
  EditionValidationError,
  EditionConflictError,
} from "../editions.server";
import { SLUG_PATTERN } from "../editions-shared";
import { allPrefixes, seriesForPrefix, seriesDataForPrefix } from "../cable-config.server";
import { createLtdShopifyProduct } from "../shopify-products.server";

export async function loader({ request }) {
  await authenticate.admin(request);
  // Series options come from YAML, not from cable_skus. The picker should
  // show every defined series whether or not catalog rows happen to exist
  // for it yet.
  const seriesOptions = allPrefixes().map((prefix) => ({
    prefix,
    series: seriesForPrefix(prefix),
  }));
  return json({ seriesOptions });
}

export async function action({ request }) {
  const { admin } = await authenticate.admin(request);
  const form = await request.formData();
  const seriesPrefix = String(form.get("seriesPrefix") || "").trim().toUpperCase();
  const slug = String(form.get("slug") || "").trim().toUpperCase();
  const lengthFt = String(form.get("lengthFt") || "").trim();
  const description = String(form.get("description") || "").trim();
  const eventName = String(form.get("eventName") || "").trim();
  const notes = String(form.get("notes") || "").trim();
  const createdBy = String(form.get("createdBy") || "").trim();

  let created;
  try {
    created = await createLtdEdition({
      seriesPrefix,
      slug,
      lengthFt,
      description,
      eventName,
      notes,
      createdBy,
    });
  } catch (e) {
    if (e instanceof EditionValidationError || e instanceof EditionConflictError) {
      return json(
        { error: e.message, field: e.field, values: { seriesPrefix, slug, lengthFt, description, eventName, notes, createdBy } },
        { status: 400 }
      );
    }
    console.error("createLtdEdition failed:", e);
    return json(
      { error: `Database error: ${e.message}`, values: { seriesPrefix, slug, lengthFt, description, eventName, notes, createdBy } },
      { status: 500 }
    );
  }

  // DB rows committed — try Shopify product creation. On failure, leave a
  // breadcrumb so the detail page can offer a retry.
  let shopifyError = null;
  try {
    // Resolve the default connector for this series from YAML (used by the
    // Shopify metafields helper to pick "Microphone Cable" vs "Instrument Cable").
    const seriesData = seriesDataForPrefix(seriesPrefix);
    const connectorType = seriesData?.connectors?.find((c) => (c.code ?? "") === "")?.display
      ?? seriesData?.connectors?.[0]?.display
      ?? "";
    await createLtdShopifyProduct(admin, {
      sku: created.sku,
      eventName,
      series: created.series,
      lengthFt,
      connectorType,
      description,
    });
  } catch (e) {
    console.error("createLtdShopifyProduct failed:", e);
    shopifyError = e.message;
  }

  // Preserve the embedded-app `host` (and shop) query params on the redirect
  // so the destination route's authenticate.admin call still resolves.
  const reqUrl = new URL(request.url);
  const sp = new URLSearchParams();
  for (const k of ["host", "shop", "embedded", "id_token"]) {
    const v = reqUrl.searchParams.get(k);
    if (v) sp.set(k, v);
  }
  if (shopifyError) sp.set("shopifyError", shopifyError);
  const search = sp.toString() ? `?${sp.toString()}` : "";
  return redirect(`/app/editions/${encodeURIComponent(created.sku)}${search}`);
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
const helpStyle = { fontSize: "12px", color: "#666", marginTop: "4px" };

export default function NewEdition() {
  const { seriesOptions } = useLoaderData();
  const actionData = useActionData();
  const navigation = useNavigation();
  const location = useLocation();
  const submitting = navigation.state === "submitting";

  const v = actionData?.values || {};
  const [slugLive, setSlugLive] = useState(v.slug || "");
  const [prefixLive, setPrefixLive] = useState(v.seriesPrefix || (seriesOptions[0]?.prefix || ""));
  const slugValid = !slugLive || SLUG_PATTERN.test(slugLive.toUpperCase());
  const editionsHref = { pathname: "/app/editions", search: location.search };

  return (
    <div style={{ padding: "20px", maxWidth: "640px", margin: "0 auto", fontFamily: "system-ui, -apple-system, sans-serif" }}>
      <div style={{ marginBottom: "20px" }}>
        <Link to={editionsHref} style={{ color: "#008060", textDecoration: "none", fontSize: "14px" }}>
          ← Back to editions
        </Link>
      </div>
      <h1 style={{ fontSize: "24px", marginBottom: "20px" }}>New Limited Edition</h1>

      {actionData?.error && (
        <div style={{ padding: "15px", backgroundColor: "#f8d7da", border: "1px solid #f5c6cb", borderRadius: "4px", marginBottom: "20px", color: "#721c24" }}>
          {actionData.error}
        </div>
      )}

      <Form method="post">
        <div style={fieldStyle}>
          <label style={labelStyle}>Series</label>
          <select
            name="seriesPrefix"
            value={prefixLive}
            onChange={(e) => setPrefixLive(e.target.value)}
            style={inputStyle}
            required
          >
            {seriesOptions.map((opt) => (
              <option key={opt.prefix} value={opt.prefix}>
                {opt.prefix} — {opt.series}
              </option>
            ))}
          </select>
          <div style={helpStyle}>
            New SKU will be <code>{prefixLive || "?"}-LTD-{slugLive.toUpperCase() || "SLUG"}</code>
          </div>
        </div>

        <div style={fieldStyle}>
          <label style={labelStyle}>Slug</label>
          <input
            name="slug"
            value={slugLive}
            onChange={(e) => setSlugLive(e.target.value)}
            placeholder="PHISH26"
            maxLength={12}
            style={{ ...inputStyle, textTransform: "uppercase", borderColor: slugValid ? "#ccc" : "#d72c0d" }}
            required
          />
          <div style={helpStyle}>4–12 characters, A–Z and 0–9 only.</div>
        </div>

        <div style={fieldStyle}>
          <label style={labelStyle}>Length (ft)</label>
          <input
            name="lengthFt"
            type="number"
            step="0.5"
            min="0.5"
            defaultValue={v.lengthFt || ""}
            placeholder="20"
            style={inputStyle}
            required
          />
        </div>

        <div style={fieldStyle}>
          <label style={labelStyle}>Event name</label>
          <input
            name="eventName"
            defaultValue={v.eventName || ""}
            placeholder="Phish Summer Tour 2026"
            style={inputStyle}
            required
          />
        </div>

        <div style={fieldStyle}>
          <label style={labelStyle}>Description</label>
          <textarea
            name="description"
            defaultValue={v.description || ""}
            placeholder="Tour-branded color scheme, signed by band"
            style={{ ...inputStyle, minHeight: "80px", fontFamily: "inherit" }}
          />
          <div style={helpStyle}>Shown on Shopify product page and on cable detail in greenlight.</div>
        </div>

        <div style={fieldStyle}>
          <label style={labelStyle}>Notes (internal)</label>
          <textarea
            name="notes"
            defaultValue={v.notes || ""}
            placeholder="Any internal context"
            style={{ ...inputStyle, minHeight: "60px", fontFamily: "inherit" }}
          />
        </div>

        <div style={fieldStyle}>
          <label style={labelStyle}>Created by (initials, optional)</label>
          <input
            name="createdBy"
            defaultValue={v.createdBy || ""}
            maxLength={8}
            style={inputStyle}
          />
        </div>

        <div style={{ display: "flex", gap: "10px", marginTop: "30px" }}>
          <button
            type="submit"
            disabled={submitting || !slugValid}
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
            {submitting ? "Creating…" : "Create edition"}
          </button>
          <Link
            to={editionsHref}
            style={{
              padding: "10px 24px",
              backgroundColor: "#fff",
              color: "#333",
              border: "1px solid #ddd",
              borderRadius: "4px",
              fontSize: "14px",
              textDecoration: "none",
            }}
          >
            Cancel
          </Link>
        </div>
      </Form>
    </div>
  );
}
