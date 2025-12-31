import { Page, Layout, Card, Text } from "@shopify/polaris";

export default function Settings() {
  return (
    <Page title="Settings">
      <Layout>
        <Layout.Section>
          <Card>
            <Text variant="headingLg" as="h2">
              Hello World! 🎉
            </Text>
            <Text as="p">
              This is your Greenlight app settings page. You made it!
            </Text>
          </Card>
        </Layout.Section>
      </Layout>
    </Page>
  );
}
