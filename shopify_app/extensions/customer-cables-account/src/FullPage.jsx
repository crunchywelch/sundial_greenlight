import { useEffect, useState } from "react";
import {
  reactExtension,
  useAuthenticatedAccountCustomer,
  Page,
  Card,
  ResourceItem,
  BlockStack,
  InlineStack,
  Text,
  Badge,
  Divider,
  Banner,
  Link,
  Image,
  View,
} from "@shopify/ui-extensions-react/customer-account";

const APP_URL = "https://greenlight.sundialwire.com";

export default reactExtension("customer-account.page.render", () => (
  <MyCablesPage />
));

function MyCablesPage() {
  const customer = useAuthenticatedAccountCustomer();
  const [cables, setCables] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const customerId = customer?.id;

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
      <Page title="My Cables" loading>
        <Text>Loading your cables...</Text>
      </Page>
    );
  }

  if (error) {
    return (
      <Page title="My Cables">
        <Banner status="critical" title="Error loading cables">
          <Text>{error}</Text>
        </Banner>
      </Page>
    );
  }

  if (cables.length === 0) {
    return (
      <Page title="My Cables">
        <Card padding>
          <BlockStack spacing="base" inlineAlignment="center">
            <Text emphasis="bold" size="large">
              No cables registered yet
            </Text>
            <Text appearance="subdued">
              Register a cable using the code on your cable's label.
            </Text>
            <Link to="https://sundialaudio.com/pages/register">
              Register a Cable
            </Link>
          </BlockStack>
        </Card>
      </Page>
    );
  }

  return (
    <Page title={`My Cables (${cables.length})`}>
      <Card padding>
        <BlockStack spacing="none">
          {cables.map((cable, index) => (
            <CableItem
              key={cable.serial_number}
              cable={cable}
              showDivider={index > 0}
            />
          ))}
        </BlockStack>
      </Card>
    </Page>
  );
}

function formatLength(cable) {
  if (cable.length) {
    const ft = parseFloat(cable.length);
    if (ft < 1) return `${Math.round(ft * 12)} in`;
    return `${ft} ft`;
  }
  if (cable.sku && !cable.sku.endsWith("MISC")) {
    const match = cable.sku.match(/-(\d+)/);
    if (match) return `${match[1]} ft`;
  }
  return null;
}

function CableItem({ cable, showDivider }) {
  const title = [cable.series, cable.color, cable.connector_type]
    .filter(Boolean)
    .join(" — ");
  const length = formatLength(cable);

  return (
    <>
      {showDivider && <Divider />}
      <ResourceItem>
        <InlineStack spacing="base" blockAlignment="center">
          {cable.image && (
            <View maxInlineSize={80}>
              <Image
                source={`${APP_URL}/images/${cable.image}`}
                accessibilityDescription={title || cable.sku}
              />
            </View>
          )}
          <BlockStack spacing="extraTight">
          <InlineStack spacing="base" blockAlignment="center">
            <Text emphasis="bold">{title || cable.sku}</Text>
            {cable.test_passed === true && (
              <Badge tone="success">QC Passed</Badge>
            )}
            {cable.test_passed === false && (
              <Badge tone="critical">QC Failed</Badge>
            )}
            {cable.test_passed == null && (
              <Badge tone="warning">Not Tested</Badge>
            )}
          </InlineStack>
          <InlineStack spacing="base">
            <Text appearance="subdued" size="small">
              Serial: {cable.serial_number}
            </Text>
            {length && (
              <Text appearance="subdued" size="small">{length}</Text>
            )}
            {cable.test_date && (
              <Text appearance="subdued" size="small">
                Tested: {new Date(cable.test_date).toLocaleDateString()}
              </Text>
            )}
          </InlineStack>
        </BlockStack>
        </InlineStack>
      </ResourceItem>
    </>
  );
}
