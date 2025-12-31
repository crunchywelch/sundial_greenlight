import { redirect } from "@remix-run/node";

export async function loader({ request }) {
  const url = new URL(request.url);
  const searchParams = url.searchParams.toString();
  return redirect(`/app${searchParams ? `?${searchParams}` : ""}`);
}
