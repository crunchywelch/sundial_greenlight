import { Outlet } from "@remix-run/react";
import { AppProvider } from "@shopify/polaris";
import "@shopify/polaris/build/esm/styles.css";

export default function AppLayout() {
  return (
    <AppProvider i18n={{}}>
      <Outlet />
    </AppProvider>
  );
}
