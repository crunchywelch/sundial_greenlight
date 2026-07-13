/** @jsxImportSource preact */
import "@shopify/ui-extensions/preact";
import { render } from "preact";
import { useEffect, useState } from "preact/hooks";

const APP_URL = "https://greenlight.sundialwire.com";

export default async () => {
  render(<MyCablesPage />, document.body);
};

// Read the authenticated customer once. `customer` is a signal
// (SubscribableSignalLike); `.value` is the canonical accessor. The id is a
// full gid://shopify/Customer/<id>, which the backend expects.
function getCustomerId() {
  const signal = shopify?.authenticatedAccount?.customer;
  const customer = signal?.value ?? signal?.current;
  return customer?.id ?? null;
}

function MyCablesPage() {
  const [cables, setCables] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const customerId = getCustomerId();

  useEffect(() => {
    if (!customerId) {
      setLoading(false);
      return;
    }

    async function fetchCables() {
      try {
        const resp = await fetch(
          `${APP_URL}/api/customer-cables?customerId=${encodeURIComponent(customerId)}`
        );
        if (!resp.ok) throw new Error("Failed to load cables");
        const data = await resp.json();
        setCables(data.cables || []);
      } catch (err) {
        console.error("Error fetching cables:", err);
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }

    fetchCables();
  }, [customerId]);

  if (loading) {
    return (
      <s-page heading="My Cables">
        <s-stack direction="inline" gap="base" alignItems="center">
          <s-spinner />
          <s-text>Loading your cables...</s-text>
        </s-stack>
      </s-page>
    );
  }

  if (error) {
    return (
      <s-page heading="My Cables">
        <s-banner tone="critical" heading="Error loading cables">
          <s-text>{error}</s-text>
        </s-banner>
      </s-page>
    );
  }

  if (cables.length === 0) {
    return (
      <s-page heading="My Cables">
        <s-section>
          <s-stack gap="base" alignItems="center">
            <s-heading>No cables registered yet</s-heading>
            <s-text color="subdued">
              Register a cable using the code on your cable's label.
            </s-text>
            <s-link href="https://sundialaudio.com/pages/register">
              Register a Cable
            </s-link>
          </s-stack>
        </s-section>
      </s-page>
    );
  }

  return (
    <s-page heading={`My Cables (${cables.length})`}>
      <s-section>
        <s-stack gap="none">
          {cables.map((cable, index) => (
            <CableItem
              key={cable.serial_number}
              cable={cable}
              showDivider={index > 0}
            />
          ))}
        </s-stack>
      </s-section>
    </s-page>
  );
}

function formatLength(cable) {
  if (cable.length == null) return null;
  const ft = parseFloat(cable.length);
  if (ft < 1) return `${Math.round(ft * 12)} in`;
  return `${ft} ft`;
}

function CableItem({ cable, showDivider }) {
  // For LTD and MISC cables, the description carries the meaningful
  // identifier (LTD edition name; MISC variant discriminator) — lead with
  // it. Catalog cables have a pattern color which is already in the title.
  const titleParts =
    cable.kind === "ltd" || cable.kind === "misc"
      ? [cable.description, cable.series, cable.connector_type]
      : [cable.series, cable.color, cable.connector_type];
  const title = titleParts.filter(Boolean).join(" — ");
  const length = formatLength(cable);

  return (
    <>
      {showDivider && <s-divider />}
      <s-stack direction="inline" gap="base" alignItems="center">
        {cable.image && (
          <s-box maxInlineSize="80px">
            <s-image
              src={`${APP_URL}/images/${cable.image}`}
              alt={title || cable.sku}
            />
          </s-box>
        )}
        <s-stack gap="small-400">
          <s-stack direction="inline" gap="base" alignItems="center">
            <s-text type="strong">{title || cable.sku}</s-text>
            {cable.test_passed === true && (
              <s-badge tone="success">QC Passed</s-badge>
            )}
            {cable.test_passed === false && (
              <s-badge tone="critical">QC Failed</s-badge>
            )}
            {cable.test_passed == null && (
              <s-badge tone="warning">Not Tested</s-badge>
            )}
          </s-stack>
          <s-stack direction="inline" gap="base">
            <s-text color="subdued" type="small">
              Serial: {cable.serial_number}
            </s-text>
            {length && (
              <s-text color="subdued" type="small">{length}</s-text>
            )}
            {cable.test_date && (
              <s-text color="subdued" type="small">
                Tested: {new Date(cable.test_date).toLocaleDateString()}
              </s-text>
            )}
          </s-stack>
        </s-stack>
      </s-stack>
    </>
  );
}
