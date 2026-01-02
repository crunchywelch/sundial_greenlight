import { useEffect, useState } from "react";
import {
  reactExtension,
  useApi,
  AdminBlock,
  BlockStack,
  Text,
  InlineStack,
  Box,
  Divider,
  Badge,
  Link,
} from "@shopify/ui-extensions-react/admin";

const TARGET = "admin.customer-details.block.render";
const MAX_DISPLAY = 3;

// Get length from data or derive from SKU (e.g., SC-12PW -> 12)
function getCableLength(cable) {
  if (cable.length) return `${cable.length}'`;

  // Parse length from SKU - number after first dash (skip MISC skus)
  if (cable.sku && !cable.sku.startsWith("MISC")) {
    const match = cable.sku.match(/-(\d+)/);
    if (match) return `${match[1]}'`;
  }
  return null;
}

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
      <BlockStack gap="base">
        {displayCables.map((cable, index) => (
          <Box key={cable.serial_number}>
            {index > 0 && <Divider />}
            <BlockStack gap="extraTight" paddingBlock="base">
              <InlineStack gap="base" blockAlignment="center">
                <Text fontWeight="bold">{cable.serial_number}</Text>
                {cable.test_status === "tested" ? (
                  <Badge tone="success">Tested</Badge>
                ) : (
                  <Badge tone="warning">Not Tested</Badge>
                )}
              </InlineStack>

              <Text tone="subdued" size="small">{cable.sku}</Text>

              {cable.sku?.includes("MISC") && cable.description && (
                <Text tone="subdued" size="small">{cable.description}</Text>
              )}

              <Text tone="subdued" size="small">
                {[getCableLength(cable), cable.color, cable.series].filter(Boolean).join(" ")}
                {cable.sku?.endsWith("-R") ? ", right angle" : ""}
              </Text>

              {cable.test_date && (
                <Text tone="subdued" size="small">
                  Tested: {new Date(cable.test_date).toLocaleDateString()}
                </Text>
              )}
            </BlockStack>
          </Box>
        ))}

        {hasMore && (
          <>
            <Divider />
            <Link href={`shopify:admin/apps/greenlight-2/app/customer/${numericId}/cables`}>
              View all {cables.length} cables →
            </Link>
          </>
        )}
      </BlockStack>
    </AdminBlock>
  );
}
