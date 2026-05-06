import { json } from "@remix-run/node";
import { useLoaderData } from "@remix-run/react";
import { authenticate } from "../shopify.server";
import { query } from "../db.server";
import { parseGroupSku, formatVariantSku } from "../cable-config.server";
import { CableTable } from "../components/CableTable";

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

  // Every cable in this group — assigned and available alike. Per-cable
  // variation (length, connector) and assignment status are surfaced so
  // this page works as the canonical "show me everything in SC-LTD-PHISH26"
  // view as well as the historical "who has cables in this group" view.
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
    WHERE ac.sku_group = $1
    ORDER BY (ac.shopify_gid IS NOT NULL AND ac.shopify_gid != '') DESC, ac.serial_number`,
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
          No cables registered in this group.
        </div>
      ) : (
        <CableTable cables={cables} />
      )}
    </div>
  );
}
