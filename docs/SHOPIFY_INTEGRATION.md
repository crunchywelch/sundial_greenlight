# Shopify Integration Reference

This document contains reference information for integrating with the Shopify Python API.

## Package Information

- **Repository**: https://github.com/Shopify/shopify_python_api
- **Package**: `shopify` (installed via pip)
- **Recommended API**: GraphQL (REST API being deprecated in 2025)

## Authentication

### Setup API Credentials

```python
import shopify

# Configure API (optional, for OAuth apps)
shopify.Session.setup(api_key=API_KEY, secret=API_SECRET)
```

### Create a Session

```python
# For Custom Apps or Private Apps
session = shopify.Session(shop_url, api_version, access_token)
shopify.ShopifyResource.activate_session(session)

# Temporary session (auto-clears when done)
with shopify.Session.temp(shop_url, api_version, token):
    # Execute API calls here
    pass
```

### Close Session

```python
shopify.ShopifyResource.clear_session()
```

## GraphQL Queries

### Basic GraphQL Execution

```python
result = shopify.GraphQL().execute(query_string)

# With variables
result = shopify.GraphQL().execute(query_string, variables={"key": "value"})
```

### Customer Query by ID

```graphql
query getCustomer($id: ID!) {
    customer(id: $id) {
        id
        firstName
        lastName
        email
        phone
        displayName
        createdAt
        updatedAt
        numberOfOrders
        tags
        note
        defaultAddress {
            address1
            address2
            city
            province
            country
            zip
        }
        amountSpent {
            amount
            currencyCode
        }
    }
}
```

**ID Format**: Must use GID format: `gid://shopify/Customer/{NUMERIC_ID}`

Example: `gid://shopify/Customer/544365967`

### Search Customers by Email

```graphql
query searchCustomers($query: String!) {
    customers(first: 1, query: $query) {
        edges {
            node {
                id
                firstName
                lastName
                email
                # ... other fields
            }
        }
    }
}
```

**Query Format**: Use search syntax like `email:customer@example.com`

### Customer Orders Query

```graphql
query getCustomerOrders($id: ID!, $limit: Int!) {
    customer(id: $id) {
        orders(first: $limit, reverse: true) {
            edges {
                node {
                    id
                    name
                    createdAt
                    displayFinancialStatus
                    displayFulfillmentStatus
                    totalPriceSet {
                        shopMoney {
                            amount
                            currencyCode
                        }
                    }
                    lineItems(first: 50) {
                        edges {
                            node {
                                title
                                quantity
                                sku
                                variant {
                                    id
                                    sku
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
```

## Available Customer Fields

**Basic Information:**
- `id`, `firstName`, `lastName`, `email`, `phone`, `displayName`

**Account Details:**
- `createdAt`, `updatedAt`, `state`, `verifiedEmail`, `validEmailAddress`
- `note`, `tags`, `taxExempt`, `canDelete`

**Order & Spending Data:**
- `numberOfOrders`, `amountSpent` (with `amount` and `currencyCode`)
- `lifetimeDuration`, `lastOrder`

**Address Information:**
- `defaultAddress`, `addresses`, `addressesV2` (paginated)

**Related Data:**
- `orders` (paginated connection), `events`, `image`
- `metafields` and `metafieldDefinitions`

## Processing GraphQL Results

```python
import json

result = shopify.GraphQL().execute(query, variables=variables)
data = json.loads(result)

# Check for errors
if "errors" in data:
    print(f"GraphQL errors: {data['errors']}")
    return None

# Extract data
customer = data.get("data", {}).get("customer")
```

## Environment Variables

Required configuration in `.env`:

```bash
SHOPIFY_SHOP_URL=your-store.myshopify.com
SHOPIFY_API_VERSION=2024-01
SHOPIFY_ACCESS_TOKEN=your_access_token_here
# OR
SHOPIFY_PRIVATE_APP_PASSWORD=your_private_app_password_here
```

## Implementation

Our implementation is in `greenlight/shopify_client.py` with three main functions:

1. **`get_customer_by_id(customer_id)`** - Lookup by Shopify ID
2. **`get_customer_by_email(email)`** - Search by email address
3. **`get_customer_orders(customer_id, limit=10)`** - Get order history with line items

All functions handle session management automatically (open/close).

## Legacy REST API (Not Recommended)

```python
# These still work but will be deprecated in 2025
customers = shopify.Customer.find()
customer = shopify.Customer.find(customer_id)
```

**Note**: Shopify recommends migrating to GraphQL for all new development.

## References

- [Shopify Python API GitHub](https://github.com/Shopify/shopify_python_api)
- [Shopify GraphQL Admin API Docs](https://shopify.dev/docs/api/admin-graphql)
- [Customer Query Reference](https://shopify.dev/docs/api/admin-graphql/2024-01/queries/customer)
