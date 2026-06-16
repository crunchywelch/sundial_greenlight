/**
 * App Proxy action: submit a Custom Cable Sets configuration.
 *
 * POST /apps/custom-cables/submit (JSON body from the configurator page).
 *
 * Recomputes the price server-side from custom-config.server.js (never trusts
 * the client), enforces the 100 ft minimum, then creates a Shopify DRAFT
 * ORDER — one custom line item per (length, quantity) row, priced at
 * length*$5 + $10 each. The merchant reviews the draft, confirms final
 * pricing, and sends the invoice from the Shopify admin.
 *
 * Nothing here touches the catalog SKU machinery or the database — custom
 * runs are quotes, not catalog inventory.
 */

import { json } from "@remix-run/node";
import { authenticate } from "../shopify.server.js";
import {
  PATTERNS,
  FABRICS,
  CABLE_TYPES,
  PRICING,
  colorLabel,
  unitPrice,
  quoteCustomSet,
} from "../custom-config.server.js";

const labelOf = (list, value) =>
  (list.find((x) => x.value === value) || {}).label || value || "—";

function connectorLabel(cableTypeValue, connectorValue) {
  const t = CABLE_TYPES.find((x) => x.value === cableTypeValue);
  const c = (t?.connectors || []).find((x) => x.value === connectorValue);
  return c ? c.label : connectorValue || "—";
}

function describeSpec(body) {
  const pattern = labelOf(PATTERNS, body.pattern);
  const fabric = labelOf(FABRICS, body.fabric);
  const cableType = labelOf(CABLE_TYPES, body.cableType);
  const primary = colorLabel(body.primaryColor);
  const accent = body.accentColor ? colorLabel(body.accentColor) : null;
  const accent2 = body.accentColor2 ? colorLabel(body.accentColor2) : null;
  const colors = [primary, accent, accent2].filter(Boolean).join(" / ");
  return { pattern, fabric, cableType, primary, accent, accent2, colors };
}

// Connectors are chosen per cable (per line), so the title takes the
// per-line connector label rather than reading it off the shared spec.
function lineTitle(spec, lengthFt, connector) {
  return `Custom ${spec.pattern} ${spec.cableType} cable — ${lengthFt} ft (${connector}, ${spec.fabric}, ${spec.colors})`;
}

async function gql(admin, q, variables) {
  const res = await admin.graphql(q, variables ? { variables } : undefined);
  const data = await res.json();
  if (data.errors) throw new Error(`GraphQL errors: ${JSON.stringify(data.errors)}`);
  return data.data;
}

const money = (n) => ({ amount: n.toFixed(2), currencyCode: PRICING.currency });

export async function action({ request }) {
  if (request.method !== "POST") {
    return json({ error: "Method not allowed" }, { status: 405 });
  }

  const { admin } = await authenticate.public.appProxy(request);

  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: "Invalid request body" }, { status: 400 });
  }

  const name = (body.name || "").trim();
  const email = (body.email || "").trim();
  if (!name || !email) {
    return json({ error: "Name and email are required." }, { status: 400 });
  }

  // Authoritative re-quote. quoteCustomSet throws on malformed lines.
  let quote;
  try {
    quote = quoteCustomSet(body.lines || []);
  } catch (err) {
    return json({ error: err.message }, { status: 400 });
  }
  if (!quote.meetsMinimum) {
    return json(
      { error: `Minimum order is ${quote.minTotalFeet} ft of total cable (you have ${quote.totalFeet} ft).` },
      { status: 400 }
    );
  }

  const spec = describeSpec(body);

  // quote.lines preserves the order of body.lines, so index pairs them to
  // recover each line's connector (quoteCustomSet only carries pricing fields).
  const lineItems = quote.lines.map((l, i) => {
    const connector = connectorLabel(body.cableType, (body.lines[i] || {}).connector);
    return {
      title: lineTitle(spec, l.lengthFt, connector),
      quantity: l.quantity,
      originalUnitPriceWithCurrency: money(unitPrice(l.lengthFt)),
      requiresShipping: true,
      taxable: true,
      customAttributes: [
        { key: "Length (ft)", value: String(l.lengthFt) },
        { key: "Pattern", value: spec.pattern },
        { key: "Colors", value: spec.colors },
        { key: "Fabric", value: spec.fabric },
        { key: "Connectors", value: connector },
      ],
    };
  });

  const noteLines = [
    `Custom Cable Set request from ${name}`,
    `Email: ${email}`,
    body.phone ? `Phone: ${body.phone}` : null,
    "",
    `Cable type: ${spec.cableType}`,
    `Pattern: ${spec.pattern} (${spec.fabric})`,
    `Colors: ${spec.colors}`,
    "",
    `Total: ${quote.totalFeet} ft across ${quote.totalCables} cable(s)`,
    `Estimated: $${quote.total.toFixed(2)} ` +
      `(cable $${quote.cableCost.toFixed(2)} + connectors $${quote.connectorCost.toFixed(2)})`,
    body.notes ? `\nNotes: ${body.notes}` : null,
  ].filter((x) => x !== null);

  const input = {
    email,
    note: noteLines.join("\n"),
    tags: ["custom-cable-set", "configurator"],
    lineItems,
  };

  try {
    const data = await gql(
      admin,
      `mutation draftOrderCreate($input: DraftOrderInput!) {
         draftOrderCreate(input: $input) {
           draftOrder { id name invoiceUrl }
           userErrors { field message }
         }
       }`,
      { input }
    );
    const errs = data.draftOrderCreate?.userErrors || [];
    if (errs.length > 0) {
      console.error("draftOrderCreate userErrors:", errs);
      return json({ error: "Could not create your quote. Please email custserv@sundialwire.com." }, { status: 502 });
    }
    const draft = data.draftOrderCreate?.draftOrder;
    return json({
      success: true,
      draftOrder: { id: draft?.id, name: draft?.name },
      quote: { totalFeet: quote.totalFeet, totalCables: quote.totalCables, total: quote.total },
    });
  } catch (err) {
    console.error("Custom cable submit error:", err);
    return json({ error: "Something went wrong creating your quote." }, { status: 500 });
  }
}

// A bare GET to the submit URL shouldn't 404 the proxy; bounce to the form.
export async function loader() {
  return json({ error: "POST a configuration to this endpoint." }, { status: 405 });
}
