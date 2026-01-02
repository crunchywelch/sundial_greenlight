export async function loader({ request }) {
  const url = new URL(request.url);
  const shop = url.searchParams.get("shop");
  const host = url.searchParams.get("host") || "";

  if (!shop) {
    throw new Response("Missing shop parameter", { status: 400 });
  }

  // Build the auth URL - this will happen in the top-level window
  const authUrl = `${process.env.SHOPIFY_APP_URL}/auth?shop=${encodeURIComponent(shop)}`;

  // Return HTML that uses App Bridge to redirect out of the iframe
  // The key is using postMessage to communicate with Shopify's admin frame
  const html = `
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Redirecting...</title>
    <script src="https://cdn.shopify.com/shopifycloud/app-bridge.js" data-api-key="${process.env.SHOPIFY_API_KEY}"></script>
  </head>
  <body>
    <p>Redirecting to authentication...</p>
    <script>
      (function() {
        var authUrl = "${authUrl}";

        // Use App Bridge if available
        if (window.shopify) {
          // Modern App Bridge - use the redirect to remote URL
          window.open(authUrl, "_top");
        } else {
          // Fallback - try direct redirect
          try {
            if (window.top !== window) {
              window.top.location.href = authUrl;
            } else {
              window.location.href = authUrl;
            }
          } catch (e) {
            // If cross-origin blocks window.top, redirect current frame
            window.location.href = authUrl;
          }
        }
      })();
    </script>
  </body>
</html>
`;

  return new Response(html, {
    headers: {
      "Content-Type": "text/html",
    },
  });
}
