import { useState } from "react";
import { json } from "@remix-run/node";
import { useActionData, useLoaderData, useSubmit } from "@remix-run/react";
import { authenticate } from "../shopify.server";

export async function loader({ request }) {
  await authenticate.admin(request);
  const url = new URL(request.url);
  const host = url.searchParams.get("host") || "";
  let adminPath = "";
  try {
    adminPath = atob(host);
  } catch (e) {}
  const appHandle = process.env.SHOPIFY_APP_HANDLE || "greenlight-2";
  return json({ adminPath, appHandle });
}

export async function action({ request }) {
  const { admin } = await authenticate.admin(request);
  const formData = await request.formData();
  const searchTerm = formData.get("searchTerm");

  try {
    const response = await admin.graphql(
      `#graphql
      query searchCustomers($query: String!) {
        customers(first: 10, query: $query) {
          edges { node { id firstName lastName email phone } }
        }
      }`,
      { variables: { query: searchTerm } }
    );
    const data = await response.json();
    if (data.errors) {
      return json({ error: "GraphQL query failed", details: data.errors }, { status: 500 });
    }
    return json({ customers: data.data?.customers?.edges || [] });
  } catch (error) {
    return json({ error: "Failed to search customers", message: error.message }, { status: 500 });
  }
}

export default function CustomerLookup() {
  const submit = useSubmit();
  const actionData = useActionData();
  const { adminPath, appHandle } = useLoaderData();
  const [search, setSearch] = useState("");

  const customers = actionData?.customers || [];

  const handleSearch = (e) => {
    e.preventDefault();
    const formData = new FormData();
    formData.append("searchTerm", search);
    submit(formData, { method: "post" });
  };

  return (
    <div style={{ padding: "0 20px 20px", maxWidth: "1200px", margin: "0 auto", fontFamily: "system-ui, -apple-system, sans-serif" }}>
      <h1 style={{ fontSize: "24px", marginBottom: "20px" }}>Customer Lookup</h1>

      <div style={{ border: "1px solid #ddd", borderRadius: "8px", padding: "20px", backgroundColor: "#fff" }}>
        <form onSubmit={handleSearch} style={{ marginBottom: "20px" }}>
          <label style={{ display: "block", marginBottom: "5px", fontSize: "14px" }}>Search by name, email, or phone</label>
          <div style={{ display: "flex", gap: "10px" }}>
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Enter customer name, email, or phone..."
              style={{ flex: 1, padding: "10px", border: "1px solid #ccc", borderRadius: "4px", fontSize: "16px" }}
            />
            <button type="submit" style={{ padding: "10px 20px", backgroundColor: "#008060", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer", fontSize: "16px" }}>Search</button>
          </div>
        </form>

        {customers.length > 0 && (
          <div>
            <h3 style={{ fontSize: "16px", marginBottom: "10px" }}>Results ({customers.length}):</h3>
            {customers.map((item) => {
              const { node } = item;
              const numericId = node.id?.split("/").pop();
              return (
                <a
                  key={node.id}
                  href={`https://${adminPath}/apps/${appHandle}/app/customer/${numericId}/cables`}
                  target="_top"
                  style={{
                    display: "block",
                    padding: "15px",
                    border: "1px solid #ddd",
                    borderRadius: "4px",
                    marginBottom: "10px",
                    cursor: "pointer",
                    backgroundColor: "#fff",
                    textDecoration: "none",
                    color: "inherit",
                  }}
                >
                  <div style={{ fontWeight: "bold", fontSize: "16px", marginBottom: "4px" }}>{node.firstName} {node.lastName}</div>
                  <div style={{ fontSize: "14px", color: "#666" }}>{node.email}</div>
                  {node.phone && <div style={{ fontSize: "14px", color: "#666" }}>{node.phone}</div>}
                  <div style={{ fontSize: "13px", color: "#008060", marginTop: "8px" }}>Click to view cables →</div>
                </a>
              );
            })}
          </div>
        )}

        {customers.length === 0 && search && !actionData?.error && (
          <div style={{ padding: "20px", textAlign: "center", color: "#666" }}>
            No customers found. Try a different search term.
          </div>
        )}
      </div>
    </div>
  );
}
