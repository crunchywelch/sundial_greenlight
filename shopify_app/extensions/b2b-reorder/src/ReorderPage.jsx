/** @jsxImportSource preact */
import "@shopify/ui-extensions/preact";
import { render } from "preact";
import { useEffect, useMemo, useState } from "preact/hooks";

const APP_URL = "https://greenlight.sundialwire.com";

export default async () => {
  render(<ReorderPage />, document.body);
};

// companyLocationId is present only for authenticated B2B (business) customers;
// undefined for everyone else. It's also the pricing/ordering context we send
// to the backend.
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
  const [qty, setQty] = useState({}); // variantId -> quantity
  const [poNumber, setPoNumber] = useState("");
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [confirmation, setConfirmation] = useState(null);

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

  const setCell = (variantId, value) => {
    const n = Math.max(0, parseInt(value, 10) || 0);
    setQty((prev) => {
      const next = { ...prev };
      if (n > 0) next[variantId] = n;
      else delete next[variantId];
      return next;
    });
  };

  const totals = useMemo(() => computeTotals(catalog, qty), [catalog, qty]);

  async function submit() {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const token = await shopify.sessionToken.get();
      const lines = Object.keys(qty).map((variantId) => ({ variantId, quantity: qty[variantId] }));
      const resp = await fetch(`${APP_URL}/api/b2b-order`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ companyLocationId, lines, poNumber, note }),
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
          setQty({});
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
          Wholesale pricing for your account. Enter quantities below, review the total,
          and submit. We create a draft order and send an invoice for review and payment.
        </s-text>

        {catalog.series.map((series) => (
          <SeriesGrid
            key={series.name}
            series={series}
            lengths={catalog.lengths}
            connectors={catalog.connectors}
            qty={qty}
            setCell={setCell}
          />
        ))}

        <OrderSummary totals={totals} />

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
          disabled={submitting || totals.totalQty === 0}
          onClick={submit}
        >
          {submitting
            ? "Submitting..."
            : `Submit order (${totals.totalQty} cable${totals.totalQty === 1 ? "" : "s"}, ${money(totals.cost)})`}
        </s-button>
      </s-stack>
    </s-page>
  );
}

// One series section: a horizontally scrollable matrix of styles (rows) x
// length x connector (columns). Header is two rows: lengths spanning their three
// connector columns, then the connector labels beneath.
function SeriesGrid({ series, lengths, connectors, qty, setCell }) {
  const perLength = connectors.length;
  const template = `minmax(130px, max-content) repeat(${lengths.length * perLength}, 3.5rem)`;

  const children = [];

  // Header row 1: empty corner + length labels spanning their connectors.
  children.push(<s-grid-item key="corner1" gridColumn="span 1" />);
  for (const L of lengths) {
    children.push(
      <s-grid-item key={`len-${L}`} gridColumn={`span ${perLength}`} paddingBlock="small-200">
        <s-text fontWeight="bold">{L}'</s-text>
      </s-grid-item>
    );
  }

  // Header row 2: empty corner + connector labels.
  children.push(<s-grid-item key="corner2" gridColumn="span 1" />);
  for (const L of lengths) {
    for (const c of connectors) {
      children.push(
        <s-grid-item key={`conn-${L}-${c.code}`}>
          <s-text type="small" color="subdued">{c.label}</s-text>
        </s-grid-item>
      );
    }
  }

  // Body: one row per style.
  for (const style of series.styles) {
    children.push(
      <s-grid-item key={`style-${style.label}`} paddingBlock="small-200">
        <s-text>{style.label}</s-text>
      </s-grid-item>
    );
    for (const L of lengths) {
      for (const c of connectors) {
        const cell = style.cells[`${L}|${c.code}`];
        const key = `cell-${style.label}-${L}-${c.code}`;
        if (!cell) {
          children.push(
            <s-grid-item key={key}>
              <s-text color="subdued">-</s-text>
            </s-grid-item>
          );
          continue;
        }
        children.push(
          <s-grid-item key={key}>
            <s-number-field
              label={`${style.label} ${L} foot ${c.label}`}
              labelAccessibilityVisibility="exclusive"
              min={0}
              placeholder="0"
              value={qty[cell.variantId] ? String(qty[cell.variantId]) : ""}
              onInput={(e) => setCell(cell.variantId, e.target.value)}
            />
          </s-grid-item>
        );
      }
    }
  }

  return (
    <s-section heading={series.name}>
      <s-stack gap="small-200">
        {series.subtitle && <s-text type="small" color="subdued">{series.subtitle}</s-text>}
        <s-scroll-box>
          <s-grid gridTemplateColumns={template} columnGap="small-200" rowGap="small-100">
            {children}
          </s-grid>
        </s-scroll-box>
      </s-stack>
    </s-section>
  );
}

function OrderSummary({ totals }) {
  return (
    <s-section heading="Order summary">
      <s-stack gap="small-200">
        <SummaryRow label="Total cables" value={String(totals.totalQty)} />
        <SummaryRow label="Your cost (dealer)" value={money(totals.cost)} />
        <SummaryRow label="Retail value (MSRP)" value={money(totals.msrpTotal)} />
        <SummaryRow label="Net profit" value={money(totals.profit)} strong />
      </s-stack>
    </s-section>
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

function computeTotals(catalog, qty) {
  let totalQty = 0;
  let cost = 0;
  let msrpTotal = 0;
  if (catalog) {
    for (const series of catalog.series) {
      for (const style of series.styles) {
        for (const key in style.cells) {
          const cell = style.cells[key];
          const q = qty[cell.variantId] || 0;
          if (q > 0) {
            totalQty += q;
            cost += q * cell.wholesale;
            msrpTotal += q * cell.msrp;
          }
        }
      }
    }
  }
  return { totalQty, cost, msrpTotal, profit: msrpTotal - cost };
}
