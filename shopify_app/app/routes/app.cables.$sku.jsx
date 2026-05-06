import { json } from "@remix-run/node";
import { useLoaderData } from "@remix-run/react";
import { authenticate } from "../shopify.server";
import { query } from "../db.server";
import { parseGroupSku, formatVariantSku } from "../cable-config.server";

export async function loader({ request, params }) {
  const { admin } = await authenticate.admin(request);
  const skuGroup = decodeURIComponent(params.sku);

  // Counts (all cables in this group)
  const countResult = await query(
    `SELECT
      COUNT(*) as total,
      COUNT(*) FILTER (WHERE shopify_gid IS NOT NULL AND shopify_gid != '') as assigned,
      COUNT(*) FILTER (WHERE shopify_gid IS NULL OR shopify_gid = '') as available
    FROM audio_cables
    WHERE sku_group = $1`,
    [skuGroup]
  );
  const counts = countResult.rows[0];

  // Assigned cables only — show the per-cable variation (length, connector)
  const result = await query(
    `SELECT
      ac.serial_number,
      ac.sku_group,
      ac.length,
      ac.connector_code,
      ac.shopify_gid,
      ac.test_timestamp,
      ac.test_passed
    FROM audio_cables ac
    WHERE ac.sku_group = $1 AND ac.shopify_gid IS NOT NULL AND ac.shopify_gid != ''
    ORDER BY ac.serial_number`,
    [skuGroup]
  );

  const parsed = parseGroupSku(skuGroup);
  const cables = result.rows.map((row) => ({
    ...row,
    length: Number(row.length),
    variant_sku: formatVariantSku({
      group_sku: row.sku_group,
      length: Number(row.length),
      connector_code: row.connector_code,
    }),
  }));

  // Customer enrichment
  const customerIds = [...new Set(cables.filter((c) => c.shopify_gid).map((c) => c.shopify_gid))];
  const customerMap = {};
  for (const customerId of customerIds) {
    try {
      const response = await admin.graphql(
        `#graphql
        query getCustomer($id: ID!) {
          customer(id: $id) {
            id
            firstName
            lastName
            email
          }
        }`,
        { variables: { id: customerId } }
      );
      const data = await response.json();
      if (data.data?.customer) customerMap[customerId] = data.data.customer;
    } catch (error) {
      console.error(`Error fetching customer ${customerId}:`, error);
    }
  }

  const cablesWithCustomers = cables.map((cable) => ({
    ...cable,
    customer: cable.shopify_gid ? customerMap[cable.shopify_gid] || null : null,
    series: parsed.series,
    color_pattern: parsed.pattern_name ?? null,
  }));

  return json({
    sku_group: skuGroup,
    cables: cablesWithCustomers,
    series: parsed.series,
    color_pattern: parsed.pattern_name ?? null,
    totalCount: parseInt(counts.total),
    assignedCount: parseInt(counts.assigned),
    availableCount: parseInt(counts.available),
  });
}

export default function CablesBySkuGroup() {
  const { sku_group, cables, series, color_pattern, totalCount, assignedCount, availableCount } = useLoaderData();

  return (
    <div style={{ padding: '20px', maxWidth: '1200px', margin: '0 auto', fontFamily: 'system-ui, -apple-system, sans-serif' }}>
      <div style={{ marginBottom: '20px' }}>
        <button
          onClick={() => window.history.back()}
          style={{ color: '#008060', textDecoration: 'none', fontSize: '14px', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
        >
          ← Back
        </button>
      </div>

      <div style={{ marginBottom: '30px' }}>
        <h1 style={{ fontSize: '24px', marginBottom: '10px' }}>{sku_group}</h1>
        <div style={{ fontSize: '14px', color: '#666', marginBottom: '10px' }}>
          {[series, color_pattern].filter(Boolean).join(' · ')}
        </div>
        <div style={{ fontSize: '16px', color: '#333', display: 'flex', gap: '20px' }}>
          <span><strong>{totalCount}</strong> total</span>
          <span style={{ color: '#008060' }}><strong>{availableCount}</strong> available</span>
          <span style={{ color: '#666' }}><strong>{assignedCount}</strong> assigned</span>
        </div>
      </div>

      {cables.length === 0 ? (
        <div style={{ padding: '40px', textAlign: 'center', backgroundColor: '#f5f5f5', borderRadius: '8px', color: '#666' }}>
          No assigned cables in this group.
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '14px' }}>
            <thead>
              <tr style={{ backgroundColor: '#f5f5f5' }}>
                <th style={{ padding: '12px', textAlign: 'left', borderBottom: '2px solid #ddd' }}>Serial Number</th>
                <th style={{ padding: '12px', textAlign: 'left', borderBottom: '2px solid #ddd' }}>Variant SKU</th>
                <th style={{ padding: '12px', textAlign: 'left', borderBottom: '2px solid #ddd' }}>Test Status</th>
                <th style={{ padding: '12px', textAlign: 'left', borderBottom: '2px solid #ddd' }}>Assigned To</th>
              </tr>
            </thead>
            <tbody>
              {cables.map((cable) => {
                const isTested = cable.test_passed !== null;
                return (
                  <tr key={cable.serial_number} style={{ backgroundColor: '#fff' }}>
                    <td style={{ padding: '12px', borderBottom: '1px solid #eee', fontWeight: 'bold' }}>
                      {cable.serial_number}
                    </td>
                    <td style={{ padding: '12px', borderBottom: '1px solid #eee', color: '#666' }}>
                      <code>{cable.variant_sku}</code>
                      <div style={{ fontSize: '12px', color: '#999' }}>{cable.length}ft{cable.connector_code === '-R' ? ' · right angle' : ''}</div>
                    </td>
                    <td style={{ padding: '12px', borderBottom: '1px solid #eee' }}>
                      <span style={{
                        padding: '4px 8px',
                        borderRadius: '12px',
                        fontSize: '12px',
                        fontWeight: 'bold',
                        backgroundColor: isTested ? '#d4edda' : '#fff3cd',
                        color: isTested ? '#155724' : '#856404',
                      }}>
                        {isTested ? 'Tested' : 'Not Tested'}
                      </span>
                    </td>
                    <td style={{ padding: '12px', borderBottom: '1px solid #eee' }}>
                      {cable.customer ? (
                        <div>
                          <div style={{ fontWeight: 'bold' }}>
                            {cable.customer.firstName} {cable.customer.lastName}
                          </div>
                          <div style={{ fontSize: '12px', color: '#666' }}>{cable.customer.email}</div>
                        </div>
                      ) : (
                        <span style={{ color: '#999' }}>Unknown</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
