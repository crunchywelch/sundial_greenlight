import { redirect } from "@remix-run/node";
import shopify from "../shopify.server";

export async function loader({ request }) {
  const url = new URL(request.url);
  const shop = url.searchParams.get("shop");
  const code = url.searchParams.get("code");

  if (!shop || !code) {
    throw new Response("Missing required parameters", { status: 400 });
  }

  // Exchange code for access token and create session
  await shopify.authenticate.admin(request);

  // Redirect to app after successful auth
  return redirect(`/app?shop=${shop}`);
}
