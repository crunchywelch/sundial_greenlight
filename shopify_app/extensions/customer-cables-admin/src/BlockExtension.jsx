import { useEffect, useState } from "react";
import {
  reactExtension,
  useApi,
  AdminBlock,
  BlockStack,
  Text,
  Box,
  Badge,
  InlineStack,
  Link,
} from "@shopify/ui-extensions-react/admin";

const TARGET = "admin.customer-details.block.render";
const MAX_DISPLAY = 3;

export default reactExtension(TARGET, () => <CustomerCablesBlock />);

function CustomerCablesBlock() {
  const { data } = useApi(TARGET);
  const [cables, setCables] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Get customer ID from the admin context
  const customerId = data.selected?.[0]?.id;

  useEffect(() => {
    if (!customerId) {
      setLoading(false);
      return;
    }

    async function fetchCables() {
      try {
        // Use relative URL - Shopify resolves against app's application_url
        const response = await fetch(
          `/api/customer-cables?customerId=${encodeURIComponent(customerId)}`
        );

        if (!response.ok) {
          throw new Error("Failed to fetch cables");
        }

        const result = await response.json();
        setCables(result.cables || []);
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
      <AdminBlock title="Cables">
        <Text>Loading cables...</Text>
      </AdminBlock>
    );
  }

  if (error) {
    return (
      <AdminBlock title="Cables">
        <Text tone="critical">Error: {error}</Text>
      </AdminBlock>
    );
  }

  if (cables.length === 0) {
    return (
      <AdminBlock title="Cables">
        <Text tone="subdued">No cables assigned to this customer.</Text>
      </AdminBlock>
    );
  }

  // Extract numeric ID from GID for URL
  const numericId = customerId?.split("/").pop();
  const displayCables = cables.slice(0, MAX_DISPLAY);
  const hasMore = cables.length > MAX_DISPLAY;

  return (
    <AdminBlock title={`Cables (${cables.length})`}>
      <BlockStack gap="extraTight">
        {displayCables.map((cable) => (
          <InlineStack key={cable.serial_number} gap="base" blockAlignment="center">
            <Box inlineSize="fill">
              <Text>
                <Text fontWeight="bold">#{cable.serial_number}</Text>
                {cable.sku ? <Text tone="subdued">{` — ${cable.sku}`}</Text> : null}
              </Text>
            </Box>
            {cable.test_date ? (
              <Badge tone="success">{`Tested ${new Date(cable.test_date).toLocaleDateString()}`}</Badge>
            ) : (
              <Badge tone="warning">Not Tested</Badge>
            )}
          </InlineStack>
        ))}

        {hasMore && (
          <Link href={`shopify:admin/apps/greenlight-2/app/customer/${numericId}/cables`}>
            View all {cables.length} cables →
          </Link>
        )}
      </BlockStack>
    </AdminBlock>
  );
}
