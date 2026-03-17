import { useEffect, useState, useCallback } from "react";
import {
  reactExtension,
  useApi,
  AdminBlock,
  BlockStack,
  InlineStack,
  Text,
  Badge,
  Banner,
  Divider,
  Button,
  Box,
} from "@shopify/ui-extensions-react/admin";

const TARGET = "admin.order-details.block.render";

export default reactExtension(TARGET, () => <OrderFulfillmentBlock />);

function OrderFulfillmentBlock() {
  const { data, query } = useApi(TARGET);
  const [lineItems, setLineItems] = useState([]);
  const [customerId, setCustomerId] = useState(null);
  const [assignedCables, setAssignedCables] = useState([]);
  const [scannerActive, setScannerActive] = useState(true);
  const [banner, setBanner] = useState(null);
  const [loading, setLoading] = useState(true);
  const [lastTimestamp, setLastTimestamp] = useState(0);

  const orderId = data.selected?.[0]?.id;

  // Fetch order details via admin GraphQL
  useEffect(() => {
    if (!orderId) {
      setLoading(false);
      return;
    }

    async function fetchOrder() {
      try {
        const result = await query(
          `query getOrder($id: ID!) {
            order(id: $id) {
              customer {
                id
              }
              lineItems(first: 50) {
                edges {
                  node {
                    title
                    quantity
                    sku
                  }
                }
              }
            }
          }`,
          { variables: { id: orderId } }
        );

        const order = result?.data?.order;
        if (order) {
          setCustomerId(order.customer?.id || null);
          const items = (order.lineItems?.edges || []).map((e) => ({
            title: e.node.title,
            quantity: e.node.quantity,
            sku: e.node.sku,
          }));
          setLineItems(items);
        }
      } catch (err) {
        console.error("Error fetching order:", err);
      } finally {
        setLoading(false);
      }
    }

    fetchOrder();
  }, [orderId, query]);

  // Fetch assigned cables from our API
  const fetchAssignedCables = useCallback(async () => {
    if (!orderId) return;
    try {
      const response = await fetch(
        `/api/order-fulfillment?orderId=${encodeURIComponent(orderId)}`
      );
      if (response.ok) {
        const result = await response.json();
        setAssignedCables(result.cables || []);
      }
    } catch (err) {
      console.error("Error fetching assigned cables:", err);
    }
  }, [orderId]);

  // Initial fetch of assigned cables
  useEffect(() => {
    fetchAssignedCables();
  }, [fetchAssignedCables]);

  // Show banner with auto-dismiss
  const showBanner = useCallback((tone, title) => {
    setBanner({ tone, title });
    setTimeout(() => setBanner(null), 4000);
  }, []);

  // Assign a scanned cable
  const assignCable = useCallback(
    async (serial) => {
      if (!orderId || !customerId) {
        showBanner("warning", "Order has no customer assigned");
        return;
      }

      const lineItemSkus = lineItems.map((li) => li.sku).filter(Boolean);

      try {
        const response = await fetch("/api/order-fulfillment", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: "assignCable",
            serialNumber: serial,
            orderId,
            customerId,
            lineItemSkus,
          }),
        });

        const result = await response.json();

        if (response.ok && result.success) {
          showBanner("success", `Assigned ${serial} (${result.cable.sku})`);
          fetchAssignedCables();
        } else {
          const code = result.code;
          if (code === "NOT_FOUND") {
            showBanner("critical", `Cable ${serial} not found`);
          } else if (code === "DUPLICATE") {
            showBanner("warning", `${serial} already scanned for this order`);
            fetchAssignedCables();
          } else if (code === "ALREADY_ASSIGNED") {
            showBanner("critical", `${serial} is assigned to a different order`);
          } else if (code === "SKU_MISMATCH") {
            showBanner(
              "critical",
              `SKU mismatch: ${serial} is ${result.cableSku}, not in this order`
            );
          } else {
            showBanner("critical", result.error || "Failed to assign cable");
          }
        }
      } catch (err) {
        console.error("Error assigning cable:", err);
        showBanner("critical", "Network error assigning cable");
      }
    },
    [orderId, customerId, lineItems, showBanner, fetchAssignedCables]
  );

  // Unassign a cable
  const unassignCable = useCallback(
    async (serial) => {
      try {
        const response = await fetch("/api/order-fulfillment", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: "unassignCable",
            serialNumber: serial,
            orderId,
          }),
        });

        if (response.ok) {
          showBanner("success", `Removed ${serial}`);
          fetchAssignedCables();
        } else {
          showBanner("critical", "Failed to remove cable");
        }
      } catch (err) {
        showBanner("critical", "Network error removing cable");
      }
    },
    [orderId, showBanner, fetchAssignedCables]
  );

  // Poll for scanner events
  useEffect(() => {
    if (!scannerActive || !orderId) return;

    const interval = setInterval(async () => {
      try {
        const response = await fetch(
          `/api/order-fulfillment?since=${lastTimestamp}&_t=${Date.now()}`
        );
        const data = await response.json();

        if (data.serial && data.timestamp > lastTimestamp) {
          setLastTimestamp(data.timestamp);
          assignCable(data.serial);
        }
      } catch (err) {
        // Silently fail, will retry
      }
    }, 500);

    return () => clearInterval(interval);
  }, [scannerActive, lastTimestamp, orderId, assignCable]);

  // Calculate progress per SKU
  const skuProgress = lineItems.map((li) => {
    const scanned = assignedCables.filter((c) => c.sku === li.sku).length;
    return { ...li, scanned };
  });

  const totalNeeded = lineItems.reduce((sum, li) => sum + li.quantity, 0);
  const totalScanned = assignedCables.length;

  if (loading) {
    return (
      <AdminBlock title="Fulfillment">
        <Text>Loading order...</Text>
      </AdminBlock>
    );
  }

  if (!orderId) {
    return (
      <AdminBlock title="Fulfillment">
        <Text tone="subdued">No order selected.</Text>
      </AdminBlock>
    );
  }

  return (
    <AdminBlock title={`Fulfillment (${totalScanned}/${totalNeeded})`}>
      <BlockStack gap="base">
        {/* Scanner status */}
        <InlineStack gap="base" blockAlignment="center">
          <Text fontWeight="bold">Scanner</Text>
          {scannerActive ? (
            <Badge tone="success">Active</Badge>
          ) : (
            <Badge tone="subdued">Paused</Badge>
          )}
          <Button
            kind="plain"
            onPress={() => setScannerActive(!scannerActive)}
          >
            {scannerActive ? "Pause" : "Resume"}
          </Button>
        </InlineStack>

        {/* Scan result banner */}
        {banner && (
          <Banner tone={banner.tone} title={banner.title} />
        )}

        <Divider />

        {/* Per-SKU progress */}
        <Text fontWeight="bold">Line Items</Text>
        {skuProgress.map((item, index) => (
          <InlineStack key={index} gap="base" blockAlignment="center">
            <Box inlineSize="fill">
              <Text>
                {item.title}{item.sku ? ` (${item.sku})` : ""}
              </Text>
            </Box>
            <Badge
              tone={
                item.scanned >= item.quantity
                  ? "success"
                  : item.scanned > 0
                  ? "warning"
                  : "subdued"
              }
            >
              {item.scanned}/{item.quantity}
            </Badge>
          </InlineStack>
        ))}

        {/* Scanned cables list */}
        {assignedCables.length > 0 && (
          <>
            <Divider />
            <Text fontWeight="bold">
              Scanned Cables ({assignedCables.length})
            </Text>
            {assignedCables.map((cable) => (
              <InlineStack
                key={cable.serial_number}
                gap="base"
                blockAlignment="center"
              >
                <Box inlineSize="fill">
                  <Text>
                    <Text fontWeight="bold">#{cable.serial_number}</Text>
                    {" - "}
                    {cable.series || ""}{cable.color ? ` ${cable.color}` : ""}{cable.sku ? ` (${cable.sku})` : ""}
                  </Text>
                </Box>
                <Button
                  kind="plain"
                  tone="critical"
                  onPress={() => unassignCable(cable.serial_number)}
                >
                  Remove
                </Button>
              </InlineStack>
            ))}
          </>
        )}
      </BlockStack>
    </AdminBlock>
  );
}
