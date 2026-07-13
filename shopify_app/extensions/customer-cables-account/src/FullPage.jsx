/** @jsxImportSource preact */
import "@shopify/ui-extensions/preact";
import { render } from "preact";
import { useEffect, useState } from "preact/hooks";

const APP_URL = "https://greenlight.sundialwire.com";
// The generic placeholder image is identical for every LTD/MISC cable, so
// showing it just makes the list noisier — treat it as "no image".
const PLACEHOLDER_IMAGE = "cable-special-babies.png";

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

  const groups = groupCables(cables);

  return (
    <s-page heading={`My Cables (${cables.length})`}>
      <s-stack gap="base">
        {groups.map((group) => (
          <CableGroup key={group.key} group={group} />
        ))}
      </s-stack>
    </s-page>
  );
}

// Group cables by variant so a customer who registered 20 identical cables
// sees one row with a quantity, not 20 near-identical rows. The variant SKU
// already encodes series + length + connector, so it's the natural key.
// Insertion order is preserved, which keeps the most recently tested variant
// first (the API returns rows ordered by test_timestamp DESC).
function groupCables(cables) {
  const map = new Map();
  for (const cable of cables) {
    const key =
      cable.sku ||
      `${cable.sku_group}|${cable.prefix}|${cable.length}|${cable.connector_type}`;
    let group = map.get(key);
    if (!group) {
      group = { key, rep: cable, items: [] };
      map.set(key, group);
    }
    group.items.push(cable);
  }
  return [...map.values()];
}

function formatLength(cable) {
  if (cable.length == null) return null;
  const ft = parseFloat(cable.length);
  if (ft < 1) return `${Math.round(ft * 12)} in`;
  return `${ft} ft`;
}

function formatDate(value) {
  return new Date(value).toLocaleDateString();
}

function CableGroup({ group }) {
  const { rep, items } = group;
  const qty = items.length;

  // Catalog cables carry a meaningful pattern color (also in the image); LTD
  // and MISC cables are distinguished by their edition/variant description,
  // which we show as a secondary line rather than crammed into the heading.
  const isSpecial = rep.kind === "ltd" || rep.kind === "misc";
  const headingParts = isSpecial
    ? [rep.series, rep.connector_type]
    : [rep.series, rep.color, rep.connector_type];
  const length = formatLength(rep);
  const heading = [headingParts.filter(Boolean).join(" — "), length]
    .filter(Boolean)
    .join(" · ");
  const subline = isSpecial ? rep.description : null;

  const showImage = rep.image && rep.image !== PLACEHOLDER_IMAGE;

  return (
    <s-section heading={heading || rep.sku}>
      <s-stack direction="inline" gap="base" alignItems="start">
        {showImage && (
          <s-image
            src={`${APP_URL}/images/${rep.image}`}
            alt={heading || rep.sku}
            inlineSize="64px"
            aspectRatio="1"
            objectFit="cover"
            borderRadius="base"
          />
        )}
        <s-stack gap="small-400">
          {(qty > 1 || subline) && (
            <s-stack direction="inline" gap="small-300" alignItems="center">
              {qty > 1 && <s-badge tone="neutral">{`${qty} cables`}</s-badge>}
              {subline && (
                <s-text color="subdued" type="small">
                  {subline}
                </s-text>
              )}
            </s-stack>
          )}

          {qty > 1 ? (
            <s-details>
              <s-text slot="summary" type="small" color="subdued">
                Show serial numbers
              </s-text>
              <s-stack gap="small-400" paddingBlockStart="small-400">
                {items.map((it) => (
                  <s-stack
                    key={it.serial_number}
                    direction="inline"
                    gap="base"
                    alignItems="center"
                  >
                    <s-text type="small">{it.serial_number}</s-text>
                    {it.test_date && (
                      <s-text type="small" color="subdued">
                        {formatDate(it.test_date)}
                      </s-text>
                    )}
                  </s-stack>
                ))}
              </s-stack>
            </s-details>
          ) : (
            <s-stack direction="inline" gap="base" alignItems="center">
              <s-text color="subdued" type="small">
                Serial: {rep.serial_number}
              </s-text>
              {rep.test_date && (
                <s-text color="subdued" type="small">
                  {formatDate(rep.test_date)}
                </s-text>
              )}
            </s-stack>
          )}
        </s-stack>
      </s-stack>
    </s-section>
  );
}
