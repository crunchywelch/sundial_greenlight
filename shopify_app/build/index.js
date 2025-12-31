var __defProp = Object.defineProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: !0 });
};

// node_modules/@remix-run/dev/dist/config/defaults/entry.server.node.tsx
var entry_server_node_exports = {};
__export(entry_server_node_exports, {
  default: () => handleRequest
});
import { PassThrough } from "node:stream";
import { createReadableStreamFromReadable } from "@remix-run/node";
import { RemixServer } from "@remix-run/react";
import * as isbotModule from "isbot";
import { renderToPipeableStream } from "react-dom/server";
import { jsx } from "react/jsx-runtime";
var ABORT_DELAY = 5e3;
function handleRequest(request, responseStatusCode, responseHeaders, remixContext, loadContext) {
  return isBotRequest(request.headers.get("user-agent")) || remixContext.isSpaMode ? handleBotRequest(
    request,
    responseStatusCode,
    responseHeaders,
    remixContext
  ) : handleBrowserRequest(
    request,
    responseStatusCode,
    responseHeaders,
    remixContext
  );
}
function isBotRequest(userAgent) {
  return userAgent ? "isbot" in isbotModule && typeof isbotModule.isbot == "function" ? isbotModule.isbot(userAgent) : "default" in isbotModule && typeof isbotModule.default == "function" ? isbotModule.default(userAgent) : !1 : !1;
}
function handleBotRequest(request, responseStatusCode, responseHeaders, remixContext) {
  return new Promise((resolve, reject) => {
    let shellRendered = !1, { pipe, abort } = renderToPipeableStream(
      /* @__PURE__ */ jsx(
        RemixServer,
        {
          context: remixContext,
          url: request.url,
          abortDelay: ABORT_DELAY
        }
      ),
      {
        onAllReady() {
          shellRendered = !0;
          let body = new PassThrough(), stream = createReadableStreamFromReadable(body);
          responseHeaders.set("Content-Type", "text/html"), resolve(
            new Response(stream, {
              headers: responseHeaders,
              status: responseStatusCode
            })
          ), pipe(body);
        },
        onShellError(error) {
          reject(error);
        },
        onError(error) {
          responseStatusCode = 500, shellRendered && console.error(error);
        }
      }
    );
    setTimeout(abort, ABORT_DELAY);
  });
}
function handleBrowserRequest(request, responseStatusCode, responseHeaders, remixContext) {
  return new Promise((resolve, reject) => {
    let shellRendered = !1, { pipe, abort } = renderToPipeableStream(
      /* @__PURE__ */ jsx(
        RemixServer,
        {
          context: remixContext,
          url: request.url,
          abortDelay: ABORT_DELAY
        }
      ),
      {
        onShellReady() {
          shellRendered = !0;
          let body = new PassThrough(), stream = createReadableStreamFromReadable(body);
          responseHeaders.set("Content-Type", "text/html"), resolve(
            new Response(stream, {
              headers: responseHeaders,
              status: responseStatusCode
            })
          ), pipe(body);
        },
        onShellError(error) {
          reject(error);
        },
        onError(error) {
          responseStatusCode = 500, shellRendered && console.error(error);
        }
      }
    );
    setTimeout(abort, ABORT_DELAY);
  });
}

// app/root.jsx
var root_exports = {};
__export(root_exports, {
  default: () => App
});
import { Links, LiveReload, Meta, Outlet, Scripts, ScrollRestoration } from "@remix-run/react";
import { jsx as jsx2, jsxs } from "react/jsx-runtime";
function App() {
  return /* @__PURE__ */ jsxs("html", { lang: "en", children: [
    /* @__PURE__ */ jsxs("head", { children: [
      /* @__PURE__ */ jsx2("meta", { charSet: "utf-8" }),
      /* @__PURE__ */ jsx2("meta", { name: "viewport", content: "width=device-width,initial-scale=1" }),
      /* @__PURE__ */ jsx2(Meta, {}),
      /* @__PURE__ */ jsx2(Links, {})
    ] }),
    /* @__PURE__ */ jsxs("body", { children: [
      /* @__PURE__ */ jsx2(Outlet, {}),
      /* @__PURE__ */ jsx2(ScrollRestoration, {}),
      /* @__PURE__ */ jsx2(Scripts, {}),
      /* @__PURE__ */ jsx2(LiveReload, {})
    ] })
  ] });
}

// app/routes/api.customer-cables.jsx
var api_customer_cables_exports = {};
__export(api_customer_cables_exports, {
  loader: () => loader,
  options: () => options
});
import { json } from "@remix-run/node";
async function loader({ request }) {
  let customerId = new URL(request.url).searchParams.get("customerId");
  if (!customerId)
    return json({ error: "Customer ID is required" }, { status: 400 });
  try {
    let cables = await fetchCustomerCables(customerId);
    return json(
      { cables },
      {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type"
        }
      }
    );
  } catch (error) {
    return console.error("Error fetching customer cables:", error), json(
      { error: "Failed to fetch cables" },
      {
        status: 500,
        headers: {
          "Access-Control-Allow-Origin": "*"
        }
      }
    );
  }
}
async function options() {
  return new Response(null, {
    status: 204,
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type"
    }
  });
}
async function fetchCustomerCables(customerId) {
  return [
    {
      id: 1,
      name: "Premium XLR Cable",
      serial_number: "XLR-2024-001",
      cable_type: "XLR",
      length: "10ft",
      test_date: "2024-12-15",
      test_status: "passed"
    },
    {
      id: 2,
      name: "TRS Patch Cable",
      serial_number: "TRS-2024-042",
      cable_type: "TRS",
      length: "6ft",
      test_date: "2024-12-20",
      test_status: "passed"
    }
  ];
}

// app/routes/auth.exit-iframe.jsx
var auth_exit_iframe_exports = {};
__export(auth_exit_iframe_exports, {
  loader: () => loader2
});
async function loader2() {
  return new Response(
    `<!DOCTYPE html>
<html>
<head>
  <title>Hello World</title>
</head>
<body>
  <div style="padding: 20px; font-size: 24px; font-weight: bold;">
    Hello World!
  </div>
</body>
</html>`,
    {
      status: 200,
      headers: {
        "Content-Type": "text/html"
      }
    }
  );
}

// app/routes/auth.callback.jsx
var auth_callback_exports = {};
__export(auth_callback_exports, {
  loader: () => loader3
});
import { redirect } from "@remix-run/node";

// app/shopify.server.js
import { shopifyApp } from "@shopify/shopify-app-remix/server";
import { restResources } from "@shopify/shopify-api/rest/admin/2025-07";
var sessions = /* @__PURE__ */ new Map(), customSessionStorage = {
  async storeSession(session) {
    return sessions.set(session.id, session), !0;
  },
  async loadSession(id) {
    return sessions.get(id) || null;
  },
  async deleteSession(id) {
    return sessions.delete(id), !0;
  },
  async deleteSessions(ids) {
    return ids.forEach((id) => sessions.delete(id)), !0;
  },
  async findSessionsByShop(shop) {
    return Array.from(sessions.values()).filter((session) => session.shop === shop);
  }
}, shopify = shopifyApp({
  apiKey: process.env.SHOPIFY_API_KEY,
  apiSecretKey: process.env.SHOPIFY_API_SECRET || "",
  apiVersion: "2025-07",
  scopes: process.env.SHOPIFY_SCOPES?.split(","),
  appUrl: process.env.SHOPIFY_APP_URL || "",
  sessionStorage: customSessionStorage,
  restResources,
  isEmbeddedApp: !0,
  authPathPrefix: "/auth"
}), shopify_server_default = shopify;
var addDocumentResponseHeaders = shopify.addDocumentResponseHeaders, authenticate = shopify.authenticate, unauthenticated = shopify.unauthenticated, login = shopify.login, registerWebhooks = shopify.registerWebhooks, sessionStorage = shopify.sessionStorage;

// app/routes/auth.callback.jsx
async function loader3({ request }) {
  let url = new URL(request.url), shop = url.searchParams.get("shop"), code = url.searchParams.get("code");
  if (!shop || !code)
    throw new Response("Missing required parameters", { status: 400 });
  return await shopify_server_default.authenticate.admin(request), redirect(`/app?shop=${shop}`);
}

// app/routes/app.settings.jsx
var app_settings_exports = {};
__export(app_settings_exports, {
  default: () => Settings
});
import { Page, Layout, Card, Text } from "@shopify/polaris";
import { jsx as jsx3, jsxs as jsxs2 } from "react/jsx-runtime";
function Settings() {
  return /* @__PURE__ */ jsx3(Page, { title: "Settings", children: /* @__PURE__ */ jsx3(Layout, { children: /* @__PURE__ */ jsx3(Layout.Section, { children: /* @__PURE__ */ jsxs2(Card, { children: [
    /* @__PURE__ */ jsx3(Text, { variant: "headingLg", as: "h2", children: "Hello World! \u{1F389}" }),
    /* @__PURE__ */ jsx3(Text, { as: "p", children: "This is your Greenlight app settings page. You made it!" })
  ] }) }) }) });
}

// app/routes/app._index.jsx
var app_index_exports = {};
__export(app_index_exports, {
  default: () => Index
});
import { jsx as jsx4 } from "react/jsx-runtime";
function Index() {
  return /* @__PURE__ */ jsx4("div", { style: { padding: "20px", fontSize: "24px", fontWeight: "bold" }, children: "Hello World!" });
}

// app/routes/auth.login.jsx
var auth_login_exports = {};
__export(auth_login_exports, {
  loader: () => loader4
});
import { redirect as redirect2 } from "@remix-run/node";
async function loader4({ request }) {
  let shop = new URL(request.url).searchParams.get("shop");
  if (!shop)
    throw new Response("Missing shop parameter", { status: 400 });
  return redirect2(`/auth?shop=${shop}`);
}

// app/routes/_index.jsx
var index_exports = {};
__export(index_exports, {
  loader: () => loader5
});
import { redirect as redirect3 } from "@remix-run/node";
async function loader5({ request }) {
  let searchParams = new URL(request.url).searchParams.toString();
  return redirect3(`/app${searchParams ? `?${searchParams}` : ""}`);
}

// app/routes/auth.jsx
var auth_exports = {};
__export(auth_exports, {
  loader: () => loader6
});
import { redirect as redirect4 } from "@remix-run/node";
async function loader6({ request }) {
  let shop = new URL(request.url).searchParams.get("shop");
  if (!shop)
    throw new Response("Missing shop parameter", { status: 400 });
  let authUrl = `https://${shop}/admin/oauth/authorize?client_id=${process.env.SHOPIFY_API_KEY}&scope=${process.env.SHOPIFY_SCOPES}&redirect_uri=${process.env.SHOPIFY_APP_URL}/auth/callback`;
  return redirect4(authUrl);
}

// app/routes/app.jsx
var app_exports = {};
__export(app_exports, {
  default: () => AppLayout
});
import { Outlet as Outlet2 } from "@remix-run/react";
import { jsx as jsx5 } from "react/jsx-runtime";
function AppLayout() {
  return /* @__PURE__ */ jsx5(Outlet2, {});
}

// server-assets-manifest:@remix-run/dev/assets-manifest
var assets_manifest_default = { entry: { module: "/build/entry.client-W22HAFXH.js", imports: ["/build/_shared/chunk-LQQIVBO6.js", "/build/_shared/chunk-O3WTSDCE.js", "/build/_shared/chunk-4HXKWYDW.js", "/build/_shared/chunk-Q3IECNXJ.js"] }, routes: { root: { id: "root", parentId: void 0, path: "", index: void 0, caseSensitive: void 0, module: "/build/root-HR5QIH6S.js", imports: void 0, hasAction: !1, hasLoader: !1, hasClientAction: !1, hasClientLoader: !1, hasErrorBoundary: !1 }, "routes/_index": { id: "routes/_index", parentId: "root", path: void 0, index: !0, caseSensitive: void 0, module: "/build/routes/_index-BUC4YXZK.js", imports: void 0, hasAction: !1, hasLoader: !0, hasClientAction: !1, hasClientLoader: !1, hasErrorBoundary: !1 }, "routes/api.customer-cables": { id: "routes/api.customer-cables", parentId: "root", path: "api/customer-cables", index: void 0, caseSensitive: void 0, module: "/build/routes/api.customer-cables-O3GNKQGX.js", imports: void 0, hasAction: !1, hasLoader: !0, hasClientAction: !1, hasClientLoader: !1, hasErrorBoundary: !1 }, "routes/app": { id: "routes/app", parentId: "root", path: "app", index: void 0, caseSensitive: void 0, module: "/build/routes/app-3L6PE2NU.js", imports: void 0, hasAction: !1, hasLoader: !1, hasClientAction: !1, hasClientLoader: !1, hasErrorBoundary: !1 }, "routes/app._index": { id: "routes/app._index", parentId: "routes/app", path: void 0, index: !0, caseSensitive: void 0, module: "/build/routes/app._index-GHMVHI75.js", imports: void 0, hasAction: !1, hasLoader: !1, hasClientAction: !1, hasClientLoader: !1, hasErrorBoundary: !1 }, "routes/app.settings": { id: "routes/app.settings", parentId: "routes/app", path: "settings", index: void 0, caseSensitive: void 0, module: "/build/routes/app.settings-R7LRNR2A.js", imports: void 0, hasAction: !1, hasLoader: !1, hasClientAction: !1, hasClientLoader: !1, hasErrorBoundary: !1 }, "routes/auth": { id: "routes/auth", parentId: "root", path: "auth", index: void 0, caseSensitive: void 0, module: "/build/routes/auth-4FQKAAKP.js", imports: void 0, hasAction: !1, hasLoader: !0, hasClientAction: !1, hasClientLoader: !1, hasErrorBoundary: !1 }, "routes/auth.callback": { id: "routes/auth.callback", parentId: "routes/auth", path: "callback", index: void 0, caseSensitive: void 0, module: "/build/routes/auth.callback-GELN3GXL.js", imports: void 0, hasAction: !1, hasLoader: !0, hasClientAction: !1, hasClientLoader: !1, hasErrorBoundary: !1 }, "routes/auth.exit-iframe": { id: "routes/auth.exit-iframe", parentId: "routes/auth", path: "exit-iframe", index: void 0, caseSensitive: void 0, module: "/build/routes/auth.exit-iframe-XRIAGDFO.js", imports: void 0, hasAction: !1, hasLoader: !0, hasClientAction: !1, hasClientLoader: !1, hasErrorBoundary: !1 }, "routes/auth.login": { id: "routes/auth.login", parentId: "routes/auth", path: "login", index: void 0, caseSensitive: void 0, module: "/build/routes/auth.login-ZR6YR4MY.js", imports: void 0, hasAction: !1, hasLoader: !0, hasClientAction: !1, hasClientLoader: !1, hasErrorBoundary: !1 } }, version: "c39d5472", hmr: void 0, url: "/build/manifest-C39D5472.js" };

// server-entry-module:@remix-run/dev/server-build
var mode = "production", assetsBuildDirectory = "public/build", future = { v3_fetcherPersist: !1, v3_relativeSplatPath: !1, v3_throwAbortReason: !1, v3_routeConfig: !1, v3_singleFetch: !1, v3_lazyRouteDiscovery: !1, unstable_optimizeDeps: !1 }, publicPath = "/build/", entry = { module: entry_server_node_exports }, routes = {
  root: {
    id: "root",
    parentId: void 0,
    path: "",
    index: void 0,
    caseSensitive: void 0,
    module: root_exports
  },
  "routes/api.customer-cables": {
    id: "routes/api.customer-cables",
    parentId: "root",
    path: "api/customer-cables",
    index: void 0,
    caseSensitive: void 0,
    module: api_customer_cables_exports
  },
  "routes/auth.exit-iframe": {
    id: "routes/auth.exit-iframe",
    parentId: "routes/auth",
    path: "exit-iframe",
    index: void 0,
    caseSensitive: void 0,
    module: auth_exit_iframe_exports
  },
  "routes/auth.callback": {
    id: "routes/auth.callback",
    parentId: "routes/auth",
    path: "callback",
    index: void 0,
    caseSensitive: void 0,
    module: auth_callback_exports
  },
  "routes/app.settings": {
    id: "routes/app.settings",
    parentId: "routes/app",
    path: "settings",
    index: void 0,
    caseSensitive: void 0,
    module: app_settings_exports
  },
  "routes/app._index": {
    id: "routes/app._index",
    parentId: "routes/app",
    path: void 0,
    index: !0,
    caseSensitive: void 0,
    module: app_index_exports
  },
  "routes/auth.login": {
    id: "routes/auth.login",
    parentId: "routes/auth",
    path: "login",
    index: void 0,
    caseSensitive: void 0,
    module: auth_login_exports
  },
  "routes/_index": {
    id: "routes/_index",
    parentId: "root",
    path: void 0,
    index: !0,
    caseSensitive: void 0,
    module: index_exports
  },
  "routes/auth": {
    id: "routes/auth",
    parentId: "root",
    path: "auth",
    index: void 0,
    caseSensitive: void 0,
    module: auth_exports
  },
  "routes/app": {
    id: "routes/app",
    parentId: "root",
    path: "app",
    index: void 0,
    caseSensitive: void 0,
    module: app_exports
  }
};
export {
  assets_manifest_default as assets,
  assetsBuildDirectory,
  entry,
  future,
  mode,
  publicPath,
  routes
};
