import { Page, Layout, Card, Text } from "@shopify/polaris";
import { Link } from "@remix-run/react";

export default function Index() {
  return (
    <Page title="Greenlight App">
      <Layout>
        <Layout.Section>
          <Card>
            <Text variant="headingLg" as="h2">
              Welcome to Greenlight
            </Text>
            <Text as="p">
              <Link to="/app/settings">Go to Settings</Link>
            </Text>
          </Card>
        </Layout.Section>
      </Layout>
    </Page>
  );
}
