"""
Shopify API integration for customer lookup and order information
"""

import os
import logging
import shopify
import requests
from typing import Optional, Dict, Any
from dotenv import load_dotenv, set_key, find_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

# Shopify configuration from environment
SHOPIFY_SHOP_URL = os.getenv("SHOPIFY_SHOP_URL")  # e.g., "your-store.myshopify.com"
SHOPIFY_API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2024-01")
SHOPIFY_ACCESS_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN")  # For custom apps / cached token
SHOPIFY_PRIVATE_APP_PASSWORD = os.getenv("SHOPIFY_PRIVATE_APP_PASSWORD")  # For private apps
SHOPIFY_CLIENT_ID = os.getenv("SHOPIFY_CLIENT_ID")  # For client credentials grant
SHOPIFY_CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET")  # For client credentials grant

# Sundial Wire store (separate Shopify store)
SHOPIFY_WIRE_SHOP_URL = os.getenv("SHOPIFY_WIRE_SHOP_URL")
SHOPIFY_WIRE_ACCESS_TOKEN = os.getenv("SHOPIFY_WIRE_ACCESS_TOKEN")
SHOPIFY_WIRE_CLIENT_ID = os.getenv("SHOPIFY_WIRE_CLIENT_ID")
SHOPIFY_WIRE_CLIENT_SECRET = os.getenv("SHOPIFY_WIRE_CLIENT_SECRET")


def get_access_token_from_client_credentials() -> Optional[str]:
    """
    Exchange client credentials for an access token using Client Credentials Grant
    https://shopify.dev/docs/apps/build/authentication-authorization/access-tokens/client-credentials-grant

    Returns:
        Access token string if successful, None otherwise
    """
    if not SHOPIFY_SHOP_URL:
        raise ValueError("SHOPIFY_SHOP_URL not configured in .env file")

    if not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
        raise ValueError("SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET must be set in .env for client credentials grant")

    token_url = f"https://{SHOPIFY_SHOP_URL}/admin/oauth/access_token"

    payload = {
        "client_id": SHOPIFY_CLIENT_ID,
        "client_secret": SHOPIFY_CLIENT_SECRET,
        "grant_type": "client_credentials"
    }

    try:
        response = requests.post(token_url, json=payload)
        response.raise_for_status()

        data = response.json()
        access_token = data.get("access_token")

        if access_token:
            # Cache the token in .env file for future use
            env_file = find_dotenv()
            if env_file:
                set_key(env_file, "SHOPIFY_ACCESS_TOKEN", access_token)
            return access_token
        else:
            print(f"❌ No access token in response: {data}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"❌ Error getting access token: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"   Response: {e.response.text}")
        return None


def validate_token(token):
    """Check if an access token is valid by making a simple API call

    Args:
        token: Access token to validate

    Returns:
        bool: True if token is valid, False otherwise
    """
    if not token or not SHOPIFY_SHOP_URL:
        return False

    try:
        session = shopify.Session(SHOPIFY_SHOP_URL, SHOPIFY_API_VERSION, token)
        shopify.ShopifyResource.activate_session(session)

        # Simple query to test if token works
        query = "{ shop { name } }"
        result = shopify.GraphQL().execute(query)

        import json
        data = json.loads(result)

        # Check for authentication errors
        if "errors" in data:
            error_msg = str(data.get("errors", ""))
            if "Invalid API key" in error_msg or "Unauthorized" in error_msg:
                return False

        shopify.ShopifyResource.clear_session()
        return True

    except Exception as e:
        shopify.ShopifyResource.clear_session()
        return False


def get_shopify_session():
    """Create and return an active Shopify session

    Automatically validates and refreshes token if needed
    """
    if not SHOPIFY_SHOP_URL:
        raise ValueError("SHOPIFY_SHOP_URL not configured in .env file")

    # Try to get access token from environment first
    token = SHOPIFY_ACCESS_TOKEN or SHOPIFY_PRIVATE_APP_PASSWORD

    # Validate existing token
    if token and not validate_token(token):
        # Token is invalid, try to get a new one
        if SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET:
            new_token = get_access_token_from_client_credentials()
            if new_token:
                token = new_token
                # Reload environment to get the updated token
                load_dotenv(override=True)
            else:
                token = None  # Clear invalid token
        else:
            token = None  # Clear invalid token

    # If still no token available, try client credentials grant
    if not token and SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET:
        token = get_access_token_from_client_credentials()
        if token:
            # Reload environment to get the updated token
            load_dotenv(override=True)

    if not token:
        raise ValueError("Could not obtain access token. Set either SHOPIFY_ACCESS_TOKEN, SHOPIFY_PRIVATE_APP_PASSWORD, or SHOPIFY_CLIENT_ID/SHOPIFY_CLIENT_SECRET in .env")

    session = shopify.Session(SHOPIFY_SHOP_URL, SHOPIFY_API_VERSION, token)
    shopify.ShopifyResource.activate_session(session)
    return session


def close_shopify_session():
    """Close the active Shopify session"""
    shopify.ShopifyResource.clear_session()


def _get_wire_access_token() -> Optional[str]:
    """Exchange wire store client credentials for an access token.

    Same flow as get_access_token_from_client_credentials() but hits
    the Sundial Wire store URL with wire store credentials.
    Caches the token to SHOPIFY_WIRE_ACCESS_TOKEN in .env.
    """
    if not SHOPIFY_WIRE_SHOP_URL:
        raise ValueError("SHOPIFY_WIRE_SHOP_URL not configured in .env file")
    if not SHOPIFY_WIRE_CLIENT_ID or not SHOPIFY_WIRE_CLIENT_SECRET:
        raise ValueError("SHOPIFY_WIRE_CLIENT_ID and SHOPIFY_WIRE_CLIENT_SECRET must be set in .env")

    token_url = f"https://{SHOPIFY_WIRE_SHOP_URL}/admin/oauth/access_token"
    payload = {
        "client_id": SHOPIFY_WIRE_CLIENT_ID,
        "client_secret": SHOPIFY_WIRE_CLIENT_SECRET,
        "grant_type": "client_credentials"
    }
    try:
        response = requests.post(token_url, json=payload)
        response.raise_for_status()
        data = response.json()
        access_token = data.get("access_token")
        if access_token:
            env_file = find_dotenv()
            if env_file:
                set_key(env_file, "SHOPIFY_WIRE_ACCESS_TOKEN", access_token)
            return access_token
        logger.error(f"No access token in wire store response: {data}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Error getting wire store access token: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"   Response: {e.response.text}")
        return None


def _validate_wire_token(token):
    """Check if a wire store access token is valid.

    Same approach as validate_token() but targets the wire store URL.
    Important: uses SHOPIFY_WIRE_SHOP_URL, not SHOPIFY_SHOP_URL.
    """
    if not token or not SHOPIFY_WIRE_SHOP_URL:
        return False

    try:
        session = shopify.Session(SHOPIFY_WIRE_SHOP_URL, SHOPIFY_API_VERSION, token)
        shopify.ShopifyResource.activate_session(session)

        query = "{ shop { name } }"
        result = shopify.GraphQL().execute(query)

        import json
        data = json.loads(result)

        if "errors" in data:
            error_msg = str(data.get("errors", ""))
            if "Invalid API key" in error_msg or "Unauthorized" in error_msg:
                shopify.ShopifyResource.clear_session()
                return False

        shopify.ShopifyResource.clear_session()
        return True

    except Exception:
        shopify.ShopifyResource.clear_session()
        return False


def get_wire_shopify_session():
    """Create and return an active Shopify session for the Sundial Wire store.

    Mirrors get_shopify_session() but uses SHOPIFY_WIRE_* env vars.
    Validates cached token and refreshes via client credentials if stale.
    """
    if not SHOPIFY_WIRE_SHOP_URL:
        raise ValueError("SHOPIFY_WIRE_SHOP_URL not configured in .env file")

    token = SHOPIFY_WIRE_ACCESS_TOKEN

    # Validate existing token
    if token and not _validate_wire_token(token):
        if SHOPIFY_WIRE_CLIENT_ID and SHOPIFY_WIRE_CLIENT_SECRET:
            new_token = _get_wire_access_token()
            if new_token:
                token = new_token
            else:
                token = None
        else:
            token = None

    # If no token yet, try client credentials grant
    if not token and SHOPIFY_WIRE_CLIENT_ID and SHOPIFY_WIRE_CLIENT_SECRET:
        token = _get_wire_access_token()

    if not token:
        raise ValueError(
            "Could not obtain wire store access token. "
            "Set SHOPIFY_WIRE_ACCESS_TOKEN or SHOPIFY_WIRE_CLIENT_ID/SHOPIFY_WIRE_CLIENT_SECRET in .env"
        )

    session = shopify.Session(SHOPIFY_WIRE_SHOP_URL, SHOPIFY_API_VERSION, token)
    shopify.ShopifyResource.activate_session(session)
    return session


def get_customer_by_id(customer_id: str) -> Optional[Dict[str, Any]]:
    """
    Look up a customer by their Shopify ID (numeric ID or GID)

    Args:
        customer_id: Either numeric ID (e.g., "544365967") or GID (e.g., "gid://shopify/Customer/544365967")

    Returns:
        Dictionary with customer information or None if not found
    """
    try:
        session = get_shopify_session()

        # Convert numeric ID to GID format if needed
        if not customer_id.startswith("gid://"):
            customer_gid = f"gid://shopify/Customer/{customer_id}"
        else:
            customer_gid = customer_id

        # GraphQL query for customer lookup
        query = """
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
        """

        variables = {"id": customer_gid}
        result = shopify.GraphQL().execute(query, variables=variables)

        import json
        data = json.loads(result)

        if "errors" in data:
            print(f"❌ GraphQL errors: {data['errors']}")
            return None

        customer = data.get("data", {}).get("customer")
        return customer

    except Exception as e:
        print(f"❌ Error fetching customer by ID: {e}")
        return None
    finally:
        close_shopify_session()


def search_customers_by_name(name: str, limit: int = 100) -> list[Dict[str, Any]]:
    """
    Search for customers by name (first name, last name, or display name)

    Args:
        name: Customer name to search for (partial match supported)
        limit: Maximum number of results to return (default 100)

    Returns:
        List of customer dictionaries matching the search
    """
    try:
        session = get_shopify_session()

        # GraphQL query to search customers by name
        query = """
        query searchCustomers($query: String!, $limit: Int!) {
            customers(first: $limit, query: $query) {
                edges {
                    node {
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
                            phone
                        }
                        amountSpent {
                            amount
                            currencyCode
                        }
                    }
                }
            }
        }
        """

        # Shopify search syntax supports searching by name field
        # The query will match first name, last name, or display name
        variables = {"query": f"*{name}*", "limit": limit}
        result = shopify.GraphQL().execute(query, variables=variables)

        import json
        data = json.loads(result)

        if "errors" in data:
            print(f"❌ GraphQL errors: {data['errors']}")
            return []

        edges = data.get("data", {}).get("customers", {}).get("edges", [])
        return [edge["node"] for edge in edges]

    except Exception as e:
        print(f"❌ Error searching customers by name: {e}")
        return []
    finally:
        close_shopify_session()


def get_customer_by_email(email: str) -> Optional[Dict[str, Any]]:
    """
    Look up a customer by their email address

    Args:
        email: Customer's email address

    Returns:
        Dictionary with customer information or None if not found
    """
    try:
        session = get_shopify_session()

        # GraphQL query to search customers by email
        query = """
        query searchCustomers($query: String!) {
            customers(first: 1, query: $query) {
                edges {
                    node {
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
                            phone
                        }
                        amountSpent {
                            amount
                            currencyCode
                        }
                    }
                }
            }
        }
        """

        variables = {"query": f"email:{email}"}
        result = shopify.GraphQL().execute(query, variables=variables)

        import json
        data = json.loads(result)

        if "errors" in data:
            print(f"❌ GraphQL errors: {data['errors']}")
            return None

        edges = data.get("data", {}).get("customers", {}).get("edges", [])
        if edges:
            return edges[0]["node"]

        return None

    except Exception as e:
        print(f"❌ Error fetching customer by email: {e}")
        return None
    finally:
        close_shopify_session()


def get_customer_orders(customer_id: str, limit: int = 10) -> list[Dict[str, Any]]:
    """
    Get recent orders for a customer

    Args:
        customer_id: Customer's Shopify ID (numeric or GID)
        limit: Maximum number of orders to retrieve (default 10)

    Returns:
        List of order dictionaries
    """
    try:
        session = get_shopify_session()

        # Convert numeric ID to GID format if needed
        if not customer_id.startswith("gid://"):
            customer_gid = f"gid://shopify/Customer/{customer_id}"
        else:
            customer_gid = customer_id

        query = """
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
        """

        variables = {"id": customer_gid, "limit": limit}
        result = shopify.GraphQL().execute(query, variables=variables)

        import json
        data = json.loads(result)

        if "errors" in data:
            print(f"❌ GraphQL errors: {data['errors']}")
            return []

        orders = data.get("data", {}).get("customer", {}).get("orders", {}).get("edges", [])
        return [edge["node"] for edge in orders]

    except Exception as e:
        print(f"❌ Error fetching customer orders: {e}")
        return []
    finally:
        close_shopify_session()


def get_product_by_sku(sku: str) -> Optional[Dict[str, Any]]:
    """
    Look up a single product variant by SKU from the Sundial Wire Shopify store.
    Uses GraphQL for fast single-SKU lookup.

    Args:
        sku: The SKU string to search for

    Returns:
        Dictionary with product info or None if not found:
        {
            "product_title": "...",
            "variant_title": "...",
            "sku": "...",
            "handle": "...",
            "price": "29.99"
        }
    """
    try:
        session = get_wire_shopify_session()

        query = """
        query getVariantBySku($query: String!) {
            productVariants(first: 1, query: $query) {
                edges {
                    node {
                        sku
                        title
                        price
                        product {
                            title
                            handle
                        }
                    }
                }
            }
        }
        """

        # Try exact match first, then prefix match (base SKU without variant suffix)
        variables = {"query": f"sku:{sku}"}
        result = shopify.GraphQL().execute(query, variables=variables)

        import json
        data = json.loads(result)

        if "errors" in data:
            logger.warning(f"GraphQL errors looking up SKU {sku}: {data['errors']}")
            return None

        edges = data.get("data", {}).get("productVariants", {}).get("edges", [])

        # If exact match failed, try wildcard prefix search
        if not edges:
            variables = {"query": f"sku:{sku}*"}
            result = shopify.GraphQL().execute(query, variables=variables)
            data = json.loads(result)

            if "errors" in data:
                return None

            edges = data.get("data", {}).get("productVariants", {}).get("edges", [])

        if not edges:
            return None

        variant = edges[0]["node"]
        product = variant.get("product", {})

        return {
            "product_title": product.get("title", ""),
            "variant_title": variant.get("title", ""),
            "sku": variant.get("sku", sku),
            "handle": product.get("handle", ""),
            "price": variant.get("price", ""),
        }

    except Exception as e:
        logger.error(f"Error looking up SKU {sku}: {e}")
        return None
    finally:
        close_shopify_session()


def get_all_products(limit: int = 250) -> list[Dict[str, Any]]:
    """
    Get all products from Shopify with their variants and SKUs.
    Uses pagination to handle stores with many products.

    Args:
        limit: Maximum number of products per page (max 250)

    Returns:
        List of product dictionaries with variants and SKU information
    """
    try:
        session = get_shopify_session()

        all_products = []
        has_next_page = True
        cursor = None

        query = """
        query getProducts($limit: Int!, $cursor: String) {
            products(first: $limit, after: $cursor) {
                pageInfo {
                    hasNextPage
                    endCursor
                }
                edges {
                    node {
                        id
                        title
                        handle
                        productType
                        vendor
                        status
                        createdAt
                        updatedAt
                        totalInventory
                        variants(first: 100) {
                            edges {
                                node {
                                    id
                                    title
                                    sku
                                    price
                                    inventoryQuantity
                                    inventoryItem {
                                        id
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """

        while has_next_page:
            variables = {"limit": limit, "cursor": cursor}
            result = shopify.GraphQL().execute(query, variables=variables)

            import json
            data = json.loads(result)

            if "errors" in data:
                print(f"❌ GraphQL errors: {data['errors']}")
                break

            products_data = data.get("data", {}).get("products", {})
            edges = products_data.get("edges", [])
            page_info = products_data.get("pageInfo", {})

            for edge in edges:
                product = edge["node"]
                all_products.append(product)

            has_next_page = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")

        return all_products

    except Exception as e:
        print(f"❌ Error fetching products: {e}")
        return []
    finally:
        close_shopify_session()


def get_all_product_skus() -> Dict[str, Dict[str, Any]]:
    """
    Get all product SKUs from Shopify indexed by SKU.

    Returns:
        Dictionary mapping SKU -> product/variant information
        {
            "SKU-123": {
                "product_id": "gid://...",
                "product_title": "...",
                "variant_id": "gid://...",
                "variant_title": "...",
                "price": "29.99",
                "inventory_quantity": 10
            }
        }
    """
    try:
        products = get_all_products()
        sku_map = {}

        for product in products:
            product_id = product["id"]
            product_title = product["title"]

            variants = product.get("variants", {}).get("edges", [])
            for variant_edge in variants:
                variant = variant_edge["node"]
                sku = variant.get("sku", "").strip()

                if sku:
                    sku_map[sku] = {
                        "product_id": product_id,
                        "product_title": product_title,
                        "product_handle": product.get("handle"),
                        "product_type": product.get("productType"),
                        "variant_id": variant["id"],
                        "variant_title": variant.get("title"),
                        "price": variant.get("price"),
                        "inventory_quantity": variant.get("inventoryQuantity", 0),
                        "status": product.get("status")
                    }

        return sku_map

    except Exception as e:
        print(f"❌ Error fetching product SKUs: {e}")
        return {}


# Example usage / testing
if __name__ == "__main__":
    # Test customer lookup by email
    print("Testing Shopify customer lookup...\n")

    # Replace with a real customer email from your store
    test_email = "customer@example.com"

    customer = get_customer_by_email(test_email)
    if customer:
        print(f"✅ Found customer: {customer['displayName']}")
        print(f"   Email: {customer['email']}")
        print(f"   Orders: {customer['numberOfOrders']}")
        print(f"   Spent: ${customer['amountSpent']['amount']} {customer['amountSpent']['currencyCode']}")

        # Get their orders
        customer_id = customer['id']
        orders = get_customer_orders(customer_id)
        print(f"\n   Recent orders ({len(orders)}):")
        for order in orders[:3]:
            print(f"     - {order['name']}: {order['displayFulfillmentStatus']}")
    else:
        print(f"❌ Customer not found: {test_email}")
