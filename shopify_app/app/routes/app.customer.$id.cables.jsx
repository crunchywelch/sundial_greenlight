import { json } from "@remix-run/node";
import { useLoaderData } from "@remix-run/react";
import { authenticate } from "../shopify.server";
import { query } from "../db.server";
import { parseSku, seriesDataForPrefix } from "../cable-config.server";

export async function loader({ request, params }) {
  const { admin } = await authenticate.admin(request);
  const { id } = params;

  // Construct the full Shopify GID
  const customerId = `gid://shopify/Customer/${id}`;

  let customer = null;

  try {
    const response = await admin.graphql(
      `#graphql
      query getCustomer($id: ID!) {
        customer(id: $id) {
          id
          firstName
          lastName
          email
          phone
        }
      }`,
      { variables: { id: customerId } }
    );
    const data = await response.json();
    customer = data.data?.customer;
  } catch (error) {
    console.error("Error fetching customer:", error);
  }

  // Fetch cables from database. Display attrs (series, color, connector,
  // core_cable, length) are resolved from the SKU + YAML config rather
  // than read off cable_skus columns. Description and length-for-variants
  // stay on cable_skus and come through.
  const result = await query(
    `SELECT
      ac.serial_number,
      ac.sku,
      ac.test_passed,
      ac.test_timestamp,
      ac.operator,
      cs.length AS variant_length,
      cs.description
    FROM audio_cables ac
    LEFT JOIN cable_skus cs ON ac.sku = cs.sku
    WHERE ac.shopify_gid = $1
    ORDER BY ac.test_timestamp DESC NULLS LAST`,
    [customerId]
  );

  const cables = result.rows.map((row) => {
    const parsed = parseSku(row.sku);
    const seriesData = parsed.series_prefix ? seriesDataForPrefix(parsed.series_prefix) : null;
    const length = parsed.kind === "catalog" ? parsed.length : row.variant_length;
    return {
      serial_number: row.serial_number,
      sku: row.sku,
      kind: parsed.kind,
      series: parsed.series,
      color: parsed.pattern_name ?? null,
      connector_type: parsed.connector_display ?? null,
      core_cable: seriesData?.core_cable ?? null,
      length,
      description: row.description,
      test_date: row.test_timestamp,
      test_passed: row.test_passed,
      test_status: row.test_passed !== null ? "tested" : "not tested",
      operator: row.operator,
    };
  });

  return json({ customer, cables, customerId: id });
}

function formatLength(cable) {
  return cable.length != null ? `${cable.length}'` : null;
}

export default function CustomerCables() {
  const { customer, cables, customerId } = useLoaderData();

  return (
    <div style={{ padding: '20px', maxWidth: '1200px', margin: '0 auto', fontFamily: 'system-ui, -apple-system, sans-serif' }}>
      {/* Header */}
      <div style={{ marginBottom: '20px' }}>
        <button
          onClick={() => window.history.back()}
          style={{
            color: '#008060',
            textDecoration: 'none',
            fontSize: '14px',
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            padding: 0
          }}
        >
          ← Back
        </button>
      </div>

      <div style={{ marginBottom: '30px' }}>
        <h1 style={{ fontSize: '24px', marginBottom: '10px' }}>
          {customer ? `${customer.firstName} ${customer.lastName}` : `Customer #${customerId}`}
        </h1>
        {customer?.email && (
          <div style={{ fontSize: '14px', color: '#666' }}>{customer.email}</div>
        )}
        {customer?.phone && (
          <div style={{ fontSize: '14px', color: '#666' }}>{customer.phone}</div>
        )}
        <div style={{ fontSize: '16px', color: '#333', marginTop: '10px' }}>
          {cables.length} cable{cables.length !== 1 ? 's' : ''} registered
        </div>
      </div>

      {/* Cables List */}
      {cables.length === 0 ? (
        <div style={{ padding: '40px', textAlign: 'center', backgroundColor: '#f5f5f5', borderRadius: '8px', color: '#666' }}>
          No cables assigned to this customer.
        </div>
      ) : (
        <div style={{ display: 'grid', gap: '15px' }}>
          {cables.map((cable) => {
            const length = formatLength(cable);
            const isRightAngle = cable.sku?.endsWith("-R");

            return (
              <div
                key={cable.serial_number}
                style={{
                  padding: '20px',
                  border: '1px solid #ddd',
                  borderRadius: '8px',
                  backgroundColor: '#fff',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
                  <div>
                    <div style={{ fontSize: '18px', fontWeight: 'bold', marginBottom: '4px' }}>
                      {cable.serial_number}
                    </div>
                    <div style={{ fontSize: '14px', color: '#666' }}>
                      {cable.sku}
                    </div>
                    {cable.kind === "misc" && cable.description && (
                      <div style={{ fontSize: '13px', color: '#888', marginTop: '2px' }}>
                        {cable.description}
                      </div>
                    )}
                  </div>
                  <div style={{
                    padding: '4px 12px',
                    borderRadius: '12px',
                    fontSize: '12px',
                    fontWeight: 'bold',
                    backgroundColor: cable.test_status === 'tested' ? '#d4edda' : '#fff3cd',
                    color: cable.test_status === 'tested' ? '#155724' : '#856404',
                  }}>
                    {cable.test_status === 'tested' ? 'Tested' : 'Not Tested'}
                  </div>
                </div>

                <div style={{ fontSize: '14px', color: '#333', marginBottom: '8px' }}>
                  {[length, cable.color, cable.series].filter(Boolean).join(" ")}
                  {isRightAngle ? ", right angle" : ""}
                </div>

                {cable.test_status === 'tested' && (
                  <div style={{ fontSize: '13px', color: '#666', display: 'flex', gap: '20px', flexWrap: 'wrap' }}>
                    {cable.test_passed !== null && (
                      <span>{cable.test_passed ? 'Passed' : 'Failed'}</span>
                    )}
                    {cable.test_date && (
                      <span>Tested: {new Date(cable.test_date).toLocaleDateString()}</span>
                    )}
                    {cable.operator && (
                      <span>By: {cable.operator}</span>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
