import { redirect } from "@remix-run/node";
import { authenticate } from "../shopify.server";

/**
 * /app — redirect to the default tab. Embedded-app query params (host,
 * shop, embedded, id_token, etc.) are preserved on the redirect so the
 * destination route's authenticate.admin call resolves cleanly.
 */
export async function loader({ request }) {
  await authenticate.admin(request);
  const url = new URL(request.url);
  const search = url.search ? url.search : "";
  return redirect(`/app/scan${search}`);
}
