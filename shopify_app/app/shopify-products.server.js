/**
 * Shopify Admin GraphQL helpers for managing cable products.
 *
 * Mirrors the Python flow in greenlight/shopify_client.py for special-baby /
 * MISC products (productSet → publishablePublish → metafieldsSet →
 * inventorySetQuantities), parameterized so it can be used for LTD editions
 * as well as MISC editing.
 */

const SPECIAL_BABY_PRICE = "24.99";
const AUDIO_VIDEO_CABLES_CATEGORY_ID = "gid://shopify/TaxonomyCategory/el-7-7-1";
const LTD_PRODUCT_TYPE = "Limited Edition";

let _cachedLocationId = null;
let _cachedPublicationIds = null;

async function gql(admin, query, variables) {
  const response = await admin.graphql(query, variables ? { variables } : undefined);
  const data = await response.json();
  if (data.errors) {
    throw new Error(`GraphQL errors: ${JSON.stringify(data.errors)}`);
  }
  return data.data;
}

function userErrorsToString(errs) {
  if (!errs || errs.length === 0) return null;
  return errs.map((e) => `${(e.field || []).join(".")}: ${e.message}`).join("; ");
}

export async function getLocationId(admin) {
  if (_cachedLocationId) return _cachedLocationId;
  const data = await gql(admin, `{ locations(first: 1) { edges { node { id } } } }`);
  const edges = data.locations?.edges || [];
  if (edges.length === 0) throw new Error("No Shopify location found");
  _cachedLocationId = edges[0].node.id;
  return _cachedLocationId;
}

export async function getPublicationIds(admin) {
  if (_cachedPublicationIds !== null) return _cachedPublicationIds;
  const data = await gql(admin, `{ publications(first: 20) { edges { node { id } } } }`);
  const edges = data.publications?.edges || [];
  _cachedPublicationIds = edges.map((e) => e.node.id);
  return _cachedPublicationIds;
}

export async function findVariantBySku(admin, sku) {
  const data = await gql(
    admin,
    `query findVariant($query: String!) {
       productVariants(first: 1, query: $query) {
         edges { node { id inventoryItem { id } product { id } } }
       }
     }`,
    { query: `sku:${sku}` }
  );
  const edges = data.productVariants?.edges || [];
  if (edges.length === 0) return null;
  const node = edges[0].node;
  return {
    variantId: node.id,
    inventoryItemId: node.inventoryItem.id,
    productId: node.product.id,
  };
}

async function publishProductToAllChannels(admin, productId) {
  const pubIds = await getPublicationIds(admin);
  if (pubIds.length === 0) {
    console.warn("No publication IDs found; product not published to any channel");
    return;
  }
  const data = await gql(
    admin,
    `mutation publishablePublish($id: ID!, $input: [PublicationInput!]!) {
       publishablePublish(id: $id, input: $input) {
         userErrors { field message }
       }
     }`,
    { id: productId, input: pubIds.map((pid) => ({ publicationId: pid })) }
  );
  const errs = userErrorsToString(data.publishablePublish?.userErrors);
  if (errs) console.warn(`publishablePublish userErrors: ${errs}`);
}

function deriveCableType(connectorType) {
  const n = (connectorType || "").replace(/[–—]/g, "-").toUpperCase();
  return n.includes("XLR") ? "Microphone Cable" : "Instrument Cable";
}

function deriveSeriesMetafield(series) {
  const s = (series || "").toLowerCase();
  if (s.includes("studio")) return "Studio (Rayon)";
  if (s.includes("tour")) return "Touring (Cotton)";
  return series;
}

function formatLengthFt(lengthFt) {
  const n = Number(lengthFt);
  return Number.isInteger(n) ? `${n} ft` : `${n} ft`;
}

async function setProductMetafields(admin, productId, { lengthFt, series, connectorType }) {
  const metafields = [
    {
      ownerId: productId,
      namespace: "custom",
      key: "cable_length",
      value: formatLengthFt(lengthFt),
      type: "single_line_text_field",
    },
    {
      ownerId: productId,
      namespace: "custom",
      key: "series",
      value: deriveSeriesMetafield(series),
      type: "single_line_text_field",
    },
    {
      ownerId: productId,
      namespace: "custom",
      key: "cable_type",
      value: deriveCableType(connectorType),
      type: "single_line_text_field",
    },
  ];
  const data = await gql(
    admin,
    `mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
       metafieldsSet(metafields: $metafields) {
         userErrors { field message }
       }
     }`,
    { metafields }
  );
  const errs = userErrorsToString(data.metafieldsSet?.userErrors);
  if (errs) console.warn(`metafieldsSet userErrors: ${errs}`);
}

export async function setInventoryQuantity(admin, inventoryItemId, quantity) {
  const locationId = await getLocationId(admin);
  const data = await gql(
    admin,
    `mutation inventorySetQuantities($input: InventorySetQuantitiesInput!) {
       inventorySetQuantities(input: $input) {
         userErrors { field message }
       }
     }`,
    {
      input: {
        reason: "correction",
        name: "available",
        ignoreCompareQuantity: true,
        quantities: [{ inventoryItemId, locationId, quantity }],
      },
    }
  );
  const errs = userErrorsToString(data.inventorySetQuantities?.userErrors);
  if (errs) throw new Error(`inventorySetQuantities: ${errs}`);
}

/**
 * Create a Shopify product for an LTD edition. Idempotent on SKU — if a
 * variant with this SKU already exists, returns it without creating a new
 * product.
 *
 * Returns { productId, variantId, inventoryItemId, alreadyExisted }.
 */
export async function createLtdShopifyProduct(admin, { sku, eventName, series, lengthFt, connectorType, description, price }) {
  const existing = await findVariantBySku(admin, sku);
  if (existing) {
    return { ...existing, alreadyExisted: true };
  }

  const lenStr = Number.isInteger(Number(lengthFt)) ? `${parseInt(lengthFt, 10)}ft` : `${lengthFt}ft`;
  const titleParts = ["Limited Edition", eventName].filter(Boolean);
  const detailParts = [lenStr, series].filter(Boolean).join(" ");
  const title = detailParts ? `${titleParts.join(" - ")} - ${detailParts}` : titleParts.join(" - ");

  const productInput = {
    title,
    descriptionHtml: description ? `<p>${description}</p>` : "",
    productType: LTD_PRODUCT_TYPE,
    category: AUDIO_VIDEO_CABLES_CATEGORY_ID,
    tags: ["limited-edition"],
    status: "DRAFT",
    productOptions: [{ name: "Title", values: [{ name: "Default Title" }] }],
    variants: [
      {
        sku,
        price: price || SPECIAL_BABY_PRICE,
        optionValues: [{ optionName: "Title", name: "Default Title" }],
        inventoryItem: { tracked: true },
      },
    ],
  };

  const data = await gql(
    admin,
    `mutation productSet($synchronous: Boolean!, $input: ProductSetInput!) {
       productSet(synchronous: $synchronous, input: $input) {
         product {
           id
           variants(first: 1) {
             edges { node { id inventoryItem { id } } }
           }
         }
         userErrors { field message }
       }
     }`,
    { synchronous: true, input: productInput }
  );

  const errs = userErrorsToString(data.productSet?.userErrors);
  if (errs) throw new Error(`productSet: ${errs}`);

  const product = data.productSet?.product;
  if (!product) throw new Error("productSet returned no product");
  const variantEdges = product.variants?.edges || [];
  if (variantEdges.length === 0) throw new Error("productSet returned no variant");

  const variantNode = variantEdges[0].node;
  const productId = product.id;
  const variantId = variantNode.id;
  const inventoryItemId = variantNode.inventoryItem.id;

  await publishProductToAllChannels(admin, productId);

  if (lengthFt && series && connectorType) {
    await setProductMetafields(admin, productId, { lengthFt, series, connectorType });
  }

  await setInventoryQuantity(admin, inventoryItemId, 0);

  return { productId, variantId, inventoryItemId, alreadyExisted: false };
}

/** Update the descriptionHtml of a product whose variant has the given SKU. */
export async function updateProductDescriptionBySku(admin, sku, description) {
  const variant = await findVariantBySku(admin, sku);
  if (!variant) throw new Error(`No Shopify product found for SKU ${sku}`);

  const data = await gql(
    admin,
    `mutation productUpdate($input: ProductInput!) {
       productUpdate(input: $input) {
         product { id }
         userErrors { field message }
       }
     }`,
    {
      input: {
        id: variant.productId,
        descriptionHtml: description ? `<p>${description}</p>` : "",
      },
    }
  );
  const errs = userErrorsToString(data.productUpdate?.userErrors);
  if (errs) throw new Error(`productUpdate: ${errs}`);
}
