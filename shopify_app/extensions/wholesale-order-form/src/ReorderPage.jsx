/** @jsxImportSource preact */
import "@shopify/ui-extensions/preact";
import { render } from "preact";
import { useEffect, useMemo, useState } from "preact/hooks";

const APP_URL = "https://greenlight.sundialwire.com";

export default async () => {
  render(<ReorderPage />, document.body);
};

// companyLocationId is present only for authenticated B2B (business) customers.
function getCompanyLocationId() {
  const signal = shopify?.authenticatedAccount?.purchasingCompany;
  const pc = signal?.value ?? signal?.current;
  return pc?.location?.id ?? null;
}

const money = (n) => `$${(Number(n) || 0).toFixed(2)}`;

function ReorderPage() {
  const companyLocationId = getCompanyLocationId();
  if (!companyLocationId) {
    return (
      <s-page heading="Order Cables">
        <s-section>
          <s-stack gap="base">
            <s-heading>Wholesale ordering</s-heading>
            <s-text color="subdued">
              This page is for wholesale (business) accounts. If your shop should
              have access, contact custserv@sundialwire.com.
            </s-text>
          </s-stack>
        </s-section>
      </s-page>
    );
  }
  return <ReorderForm companyLocationId={companyLocationId} />;
}

function ReorderForm({ companyLocationId }) {
  const [catalog, setCatalog] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // order: variantId -> line
  const [order, setOrder] = useState({});
  const [poNumber, setPoNumber] = useState("");
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [confirmation, setConfirmation] = useState(null);

  // builder selection
  const [styleKey, setStyleKey] = useState("");
  const [length, setLength] = useState("");
  const [qtys, setQtys] = useState({});

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const token = await shopify.sessionToken.get();
        const resp = await fetch(`${APP_URL}/api/b2b-catalog`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ companyLocationId }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Could not load the wholesale catalog.");
        if (!cancelled) setCatalog(data.catalog);
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [companyLocationId]);

  const styles = useMemo(() => {
    if (!catalog) return [];
    const list = [];
    for (const s of catalog.series) {
      for (const st of s.styles) list.push({ ...st, series: s.name });
    }
    return list;
  }, [catalog]);

  // default the selectors once the catalog arrives
  useEffect(() => {
    if (styles.length && !styleKey) setStyleKey(styles[0].label);
    if (catalog && !length) setLength(String(catalog.lengths[0]));
  }, [styles, catalog]);

  const selStyle = styles.find((s) => s.label === styleKey) || null;
  const priceCell = useMemo(() => {
    if (!selStyle || !length || !catalog) return null;
    for (const c of catalog.connectors) {
      const cell = selStyle.cells[`${length}|${c.code}`];
      if (cell) return cell;
    }
    return null;
  }, [selStyle, length, catalog]);

  function addToOrder() {
    if (!selStyle || !length || !catalog) return;
    setOrder((prev) => {
      const next = { ...prev };
      for (const c of catalog.connectors) {
        const q = parseInt(qtys[c.code], 10) || 0;
        if (q <= 0) continue;
        const cell = selStyle.cells[`${length}|${c.code}`];
        if (!cell) continue;
        const existing = next[cell.variantId];
        next[cell.variantId] = {
          variantId: cell.variantId,
          styleLabel: selStyle.label,
          length: Number(length),
          connectorLabel: c.label,
          qty: (existing?.qty || 0) + q,
          wholesale: cell.wholesale,
          msrp: cell.msrp,
        };
      }
      return next;
    });
    setQtys({});
  }

  function removeLine(variantId) {
    setOrder((prev) => {
      const next = { ...prev };
      delete next[variantId];
      return next;
    });
  }

  const lines = Object.values(order);
  const totals = useMemo(() => {
    let qty = 0;
    let cost = 0;
    let msrp = 0;
    for (const l of lines) {
      qty += l.qty;
      cost += l.qty * l.wholesale;
      msrp += l.qty * l.msrp;
    }
    return { qty, cost, msrp, profit: msrp - cost };
  }, [order]);

  async function submit() {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const token = await shopify.sessionToken.get();
      const payloadLines = lines.map((l) => ({ variantId: l.variantId, quantity: l.qty }));
      const resp = await fetch(`${APP_URL}/api/b2b-order`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ companyLocationId, lines: payloadLines, poNumber, note }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "Could not submit your order.");
      setConfirmation(data);
    } catch (e) {
      setSubmitError(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <s-page heading="Order Cables">
        <s-stack direction="inline" gap="base" alignItems="center">
          <s-spinner />
          <s-text>Loading wholesale catalog...</s-text>
        </s-stack>
      </s-page>
    );
  }
  if (error) {
    return (
      <s-page heading="Order Cables">
        <s-banner tone="critical" heading="Could not load the catalog">
          <s-text>{error}</s-text>
        </s-banner>
      </s-page>
    );
  }
  if (confirmation) {
    return (
      <Confirmation
        confirmation={confirmation}
        onNew={() => {
          setConfirmation(null);
          setOrder({});
          setPoNumber("");
          setNote("");
        }}
      />
    );
  }

  return (
    <s-page heading="Order Cables">
      <s-stack gap="large-100">
        <s-text color="subdued">
          Wholesale pricing for your store. Add cables to your order below, then submit.
          We create a draft order and send an invoice to review and pay.
        </s-text>

        <s-section heading="Add cables">
          <s-stack gap="base">
            <s-select label="Style" value={styleKey} onChange={(e) => setStyleKey(e.target.value)}>
              {catalog.series.map((s) =>
                s.styles.map((st) => (
                  <s-option key={st.label} value={st.label}>
                    {`${st.label} (${s.name.replace(" Series", "")})`}
                  </s-option>
                ))
              )}
            </s-select>

            <s-select label="Length" value={length} onChange={(e) => setLength(e.target.value)}>
              {catalog.lengths.map((L) => (
                <s-option key={L} value={String(L)}>{`${L} ft`}</s-option>
              ))}
            </s-select>

            {priceCell && (
              <s-text color="subdued" type="small">
                {`Wholesale ${money(priceCell.wholesale)} each · MSRP ${money(priceCell.msrp)} · profit ${money(priceCell.msrp - priceCell.wholesale)}`}
              </s-text>
            )}

            <s-stack direction="inline" gap="base">
              {catalog.connectors.map((c) => {
                const avail = Boolean(selStyle && selStyle.cells[`${length}|${c.code}`]);
                return (
                  <s-number-field
                    key={c.code}
                    label={c.label}
                    min={0}
                    placeholder="0"
                    disabled={!avail}
                    value={qtys[c.code] || ""}
                    onInput={(e) => setQtys((q) => ({ ...q, [c.code]: e.target.value }))}
                  />
                );
              })}
            </s-stack>

            <s-button onClick={addToOrder}>Add to order</s-button>
          </s-stack>
        </s-section>

        {lines.length > 0 && (
          <s-section heading="Your order">
            <s-stack gap="small-300">
              {lines.map((l) => (
                <s-stack key={l.variantId} direction="inline" gap="base" alignItems="center">
                  <s-box inlineSize="fill">
                    <s-text>{`${l.qty} × ${l.styleLabel} ${l.length} ft ${l.connectorLabel}`}</s-text>
                  </s-box>
                  <s-text>{money(l.qty * l.wholesale)}</s-text>
                  <s-button variant="tertiary" onClick={() => removeLine(l.variantId)}>Remove</s-button>
                </s-stack>
              ))}
            </s-stack>
          </s-section>
        )}

        <s-section heading="Summary">
          <s-stack gap="small-200">
            <SummaryRow label="Total cables" value={String(totals.qty)} />
            <SummaryRow label="Your cost (dealer)" value={money(totals.cost)} />
            <SummaryRow label="Retail value (MSRP)" value={money(totals.msrp)} />
            <SummaryRow label="Net profit" value={money(totals.profit)} strong />
          </s-stack>
        </s-section>

        <s-section heading="Order details">
          <s-stack gap="base">
            <s-text-field
              label="PO number (optional)"
              value={poNumber}
              onInput={(e) => setPoNumber(e.target.value)}
            />
            <s-text-field
              label="Notes for our team (optional)"
              value={note}
              onInput={(e) => setNote(e.target.value)}
            />
          </s-stack>
        </s-section>

        {submitError && (
          <s-banner tone="critical" heading="Order not submitted">
            <s-text>{submitError}</s-text>
          </s-banner>
        )}

        <s-button
          variant="primary"
          disabled={submitting || totals.qty === 0}
          onClick={submit}
        >
          {submitting
            ? "Submitting..."
            : `Submit order (${totals.qty} cable${totals.qty === 1 ? "" : "s"}, ${money(totals.cost)})`}
        </s-button>
      </s-stack>
    </s-page>
  );
}

function SummaryRow({ label, value, strong }) {
  return (
    <s-stack direction="inline" gap="base" alignItems="center">
      <s-box inlineSize="fill">
        <s-text color="subdued">{label}</s-text>
      </s-box>
      <s-text fontWeight={strong ? "bold" : undefined}>{value}</s-text>
    </s-stack>
  );
}

function Confirmation({ confirmation, onNew }) {
  return (
    <s-page heading="Order submitted">
      <s-section>
        <s-stack gap="base">
          <s-banner tone="success" heading="Thanks! Your order was received.">
            <s-text>
              We created {confirmation.orderName ? `draft order ${confirmation.orderName}` : "your draft order"}.
              {confirmation.invoiceUrl
                ? " Use the link below to review and pay."
                : " Our team will follow up with an invoice."}
            </s-text>
          </s-banner>
          {confirmation.invoiceUrl && (
            <s-link href={confirmation.invoiceUrl} target="_blank">
              Review and pay invoice
            </s-link>
          )}
          <s-button onClick={onNew}>Start another order</s-button>
        </s-stack>
      </s-section>
    </s-page>
  );
}
