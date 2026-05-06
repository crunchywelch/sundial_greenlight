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
import { allPrefixes, seriesForPrefix } from "../cable-config.server";

export async function loader({ request }) {
  await authenticate.admin(request);
  const seriesOptions = allPrefixes().map((prefix) => ({
    prefix,
    series: seriesForPrefix(prefix),
  }));
  return json({ seriesOptions });
}

export async function action({ request }) {
  await authenticate.admin(request);
  const form = await request.formData();
  const seriesPrefix = String(form.get("seriesPrefix") || "").trim().toUpperCase();
  const slug = String(form.get("slug") || "").trim().toUpperCase();
  const description = String(form.get("description") || "").trim();

  let created;
  try {
    created = await createLtdEdition({ seriesPrefix, slug, description });
  } catch (e) {
    if (e instanceof EditionValidationError || e instanceof EditionConflictError) {
      return json(
        { error: e.message, field: e.field, values: { seriesPrefix, slug, description } },
        { status: 400 }
      );
    }
    console.error("createLtdEdition failed:", e);
    return json(
      { error: `Database error: ${e.message}`, values: { seriesPrefix, slug, description } },
      { status: 500 }
    );
  }

  // Preserve embedded-app `host` (and shop) query params on the redirect.
  const reqUrl = new URL(request.url);
  const sp = new URLSearchParams();
  for (const k of ["host", "shop", "embedded", "id_token"]) {
    const v = reqUrl.searchParams.get(k);
    if (v) sp.set(k, v);
  }
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

      <p style={{ color: "#666", fontSize: "13px", marginBottom: "20px" }}>
        Editions are tags. Cables registered against this edition carry their own length, connector, and other attributes.
      </p>

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
          <label style={labelStyle}>Description</label>
          <textarea
            name="description"
            defaultValue={v.description || ""}
            placeholder="Phish Summer Tour 2026"
            style={{ ...inputStyle, minHeight: "80px", fontFamily: "inherit" }}
            required
          />
          <div style={helpStyle}>Free text identifying this edition. Shown wherever the edition is referenced.</div>
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
