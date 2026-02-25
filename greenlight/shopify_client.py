"""
Shopify API integration for customer lookup, order information, and inventory management
"""

import os
import json
import logging
import shopify
import requests
import yaml
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
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

# Module-level caches for inventory operations (stable within a session)
_cached_location_id: Optional[str] = None
_cached_publication_ids: Optional[list] = None
_inventory_item_cache: Dict[str, str] = {}


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
            # Update in-process env so get_shopify_session() picks it up immediately
            os.environ["SHOPIFY_ACCESS_TOKEN"] = access_token
            # Also persist to .env file for next app restart
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

    # Read token from os.environ (not module-level var) so refreshed tokens are picked up
    token = os.getenv("SHOPIFY_ACCESS_TOKEN") or os.getenv("SHOPIFY_PRIVATE_APP_PASSWORD")

    # Validate existing token
    if token and not validate_token(token):
        # Token is invalid, try to get a new one
        if SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET:
            new_token = get_access_token_from_client_credentials()
            if new_token:
                token = new_token
            else:
                token = None  # Clear invalid token
        else:
            token = None  # Clear invalid token

    # If still no token available, try client credentials grant
    if not token and SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET:
        token = get_access_token_from_client_credentials()

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


def _get_location_id() -> Optional[str]:
    """Get the primary location ID for the main Shopify store.

    Cached after first call since location never changes during a session.
    """
    global _cached_location_id
    if _cached_location_id:
        return _cached_location_id

    try:
        session = get_shopify_session()
        query = "{ locations(first: 1) { edges { node { id } } } }"
        result = shopify.GraphQL().execute(query)
        data = json.loads(result)

        if "errors" in data:
            logger.error(f"GraphQL errors fetching location: {data['errors']}")
            return None

        edges = data.get("data", {}).get("locations", {}).get("edges", [])
        if edges:
            _cached_location_id = edges[0]["node"]["id"]
            return _cached_location_id
        return None
    except Exception as e:
        logger.error(f"Error fetching location ID: {e}")
        return None
    finally:
        close_shopify_session()


def _get_publication_ids() -> list:
    """Get all publication (sales channel) IDs for the main Shopify store.

    Cached after first call since channels rarely change during a session.
    """
    global _cached_publication_ids
    if _cached_publication_ids is not None:
        return _cached_publication_ids

    try:
        session = get_shopify_session()
        query = "{ publications(first: 20) { edges { node { id } } } }"
        result = shopify.GraphQL().execute(query)
        data = json.loads(result)

        if "errors" in data:
            logger.error(f"GraphQL errors fetching publications: {data['errors']}")
            return []

        edges = data.get("data", {}).get("publications", {}).get("edges", [])
        _cached_publication_ids = [edge["node"]["id"] for edge in edges]
        return _cached_publication_ids
    except Exception as e:
        logger.error(f"Error fetching publication IDs: {e}")
        return []
    finally:
        close_shopify_session()


def _publish_product_to_all_channels(product_id: str) -> bool:
    """Publish a product to all sales channels.

    Returns True if successful, False otherwise. Logs but does not raise on failure.
    """
    pub_ids = _get_publication_ids()
    if not pub_ids:
        logger.warning("No publication IDs found; product not published to any channel")
        return False

    try:
        session = get_shopify_session()
        mutation = """
        mutation publishablePublish($id: ID!, $input: [PublicationInput!]!) {
            publishablePublish(id: $id, input: $input) {
                userErrors { field message }
            }
        }
        """
        variables = {
            "id": product_id,
            "input": [{"publicationId": pid} for pid in pub_ids],
        }
        result = shopify.GraphQL().execute(mutation, variables=variables)
        data = json.loads(result)

        if "errors" in data:
            logger.error(f"GraphQL errors publishing product: {data['errors']}")
            return False

        user_errors = data.get("data", {}).get("publishablePublish", {}).get("userErrors", [])
        if user_errors:
            logger.error(f"User errors publishing product: {user_errors}")
            return False

        logger.info(f"Published product {product_id} to {len(pub_ids)} channels")
        return True
    except Exception as e:
        logger.error(f"Error publishing product to channels: {e}")
        return False
    finally:
        close_shopify_session()


def _get_inventory_item_id(sku: str) -> Optional[str]:
    """Look up the Shopify InventoryItem GID for a SKU.

    Results are cached per-SKU so repeated calls are free.
    """
    if sku in _inventory_item_cache:
        return _inventory_item_cache[sku]

    try:
        session = get_shopify_session()
        query = """
        query getInventoryItem($query: String!) {
            productVariants(first: 1, query: $query) {
                edges {
                    node {
                        sku
                        inventoryItem {
                            id
                        }
                    }
                }
            }
        }
        """
        variables = {"query": f"sku:{sku}"}
        result = shopify.GraphQL().execute(query, variables=variables)
        data = json.loads(result)

        if "errors" in data:
            logger.error(f"GraphQL errors looking up inventory item for {sku}: {data['errors']}")
            return None

        edges = data.get("data", {}).get("productVariants", {}).get("edges", [])
        if edges:
            inv_item_id = edges[0]["node"]["inventoryItem"]["id"]
            _inventory_item_cache[sku] = inv_item_id
            return inv_item_id
        logger.warning(f"No product variant found for SKU: {sku}")
        return None
    except Exception as e:
        logger.error(f"Error looking up inventory item for SKU {sku}: {e}")
        return None
    finally:
        close_shopify_session()


def set_inventory_for_sku(sku: str, quantity: int) -> Tuple[bool, Optional[str]]:
    """Set Shopify available inventory for a SKU to an absolute quantity.

    Args:
        sku: Product variant SKU
        quantity: Desired available quantity

    Returns:
        (success, error_message) tuple. Never raises.
    """
    try:
        inventory_item_id = _get_inventory_item_id(sku)
        if not inventory_item_id:
            return False, f"No inventory item found for SKU: {sku}"

        location_id = _get_location_id()
        if not location_id:
            return False, "Could not determine Shopify location"

        session = get_shopify_session()
        mutation = """
        mutation inventorySetQuantities($input: InventorySetQuantitiesInput!) {
            inventorySetQuantities(input: $input) {
                userErrors {
                    field
                    message
                }
                inventoryAdjustmentGroup {
                    changes {
                        name
                        delta
                    }
                }
            }
        }
        """
        variables = {
            "input": {
                "reason": "correction",
                "name": "available",
                "ignoreCompareQuantity": True,
                "quantities": [
                    {
                        "inventoryItemId": inventory_item_id,
                        "locationId": location_id,
                        "quantity": quantity,
                    }
                ],
            }
        }
        result = shopify.GraphQL().execute(mutation, variables=variables)
        data = json.loads(result)

        if "errors" in data:
            err = str(data["errors"])
            logger.error(f"GraphQL errors setting inventory for {sku}: {err}")
            return False, err

        user_errors = data.get("data", {}).get("inventorySetQuantities", {}).get("userErrors", [])
        if user_errors:
            err = "; ".join(e["message"] for e in user_errors)
            logger.error(f"Shopify user errors setting inventory for {sku}: {err}")
            return False, err

        logger.info(f"Shopify inventory set to {quantity} for SKU {sku}")
        return True, None
    except Exception as e:
        err = str(e)
        logger.error(f"Error setting Shopify inventory for {sku}: {err}")
        return False, err
    finally:
        try:
            close_shopify_session()
        except Exception:
            pass


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
                    inv_item = variant.get("inventoryItem") or {}
                    sku_map[sku] = {
                        "product_id": product_id,
                        "product_title": product_title,
                        "product_handle": product.get("handle"),
                        "product_type": product.get("productType"),
                        "variant_id": variant["id"],
                        "variant_title": variant.get("title"),
                        "price": variant.get("price"),
                        "inventory_quantity": variant.get("inventoryQuantity", 0),
                        "inventory_item_id": inv_item.get("id"),
                        "status": product.get("status")
                    }

        return sku_map

    except Exception as e:
        print(f"❌ Error fetching product SKUs: {e}")
        return {}


# --- Special Baby (MISC cable) support ---

SPECIAL_BABY_PRICE = "24.99"
SPECIAL_BABY_PRODUCT_TYPE = "Special Baby"
AUDIO_VIDEO_CABLES_CATEGORY_ID = "gid://shopify/TaxonomyCategory/el-7-7-1"

# Map series slug to a human-readable name for product titles
_SERIES_DISPLAY = {
    "standard": "Standard",
    "signature": "Signature",
    "tour_classic": "Tour Classic",
    "tour_select": "Tour Select",
}

# Load materials data for weight calculation
_MATERIALS_PATH = Path(__file__).resolve().parent.parent / "util" / "product_lines" / "materials.yaml"
_materials_data: Optional[Dict] = None


def _load_materials() -> Dict:
    """Load and cache materials.yaml for weight calculations."""
    global _materials_data
    if _materials_data is not None:
        return _materials_data
    try:
        with open(_MATERIALS_PATH) as f:
            _materials_data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"Could not load materials.yaml: {e}")
        _materials_data = {}
    return _materials_data


def _calculate_cable_weight_oz(length_ft: float, connector_type: str, core_cable: str) -> Optional[float]:
    """Calculate cable weight in ounces from component weights.

    Formula: cable_per_foot * length + connector_a_weight + connector_b_weight

    Args:
        length_ft: Cable length in feet
        connector_type: e.g. "TS\u2013TS", "RA\u2013TS", "XLR\u2013XLR"
        core_cable: e.g. "Canare GS-6", "Canare L-4E6S"

    Returns:
        Weight in ounces, or None if materials data is missing.
    """
    materials = _load_materials()
    cable_rates = materials.get("cable_per_foot", {})
    connectors = materials.get("connectors", {})

    if not cable_rates or not connectors:
        return None

    # Extract cable model from full name (e.g. "Canare GS-6" -> "GS-6")
    cable_key = core_cable.split()[-1] if core_cable else ""
    rate = cable_rates.get(cable_key)
    if rate is None:
        logger.warning(f"No cable_per_foot entry for '{cable_key}'")
        return None

    # Map connector_type to two connector weight keys
    # Normalize en-dash/em-dash to hyphen
    normalized = (connector_type or "").replace("\u2013", "-").replace("\u2014", "-").upper()

    connector_map = {
        "TS-TS": ("TS_straight", "TS_straight"),
        "RA-TS": ("TS_right_angle", "TS_straight"),
        "TS-RA": ("TS_straight", "TS_right_angle"),
        "XLR-XLR": ("XLR", "XLR"),
    }
    pair = connector_map.get(normalized)
    if not pair:
        logger.warning(f"Unknown connector_type for weight calc: '{connector_type}'")
        return None

    w_a = connectors.get(pair[0])
    w_b = connectors.get(pair[1])
    if w_a is None or w_b is None:
        logger.warning(f"Missing connector weight for {pair}")
        return None

    return round(rate * length_ft + w_a + w_b, 1)


# Default cable attributes by series (used when cable_skus has "Varies" for MISC SKUs)
_SERIES_CABLE_DEFAULTS = {
    "Studio Classic":      {"core_cable": "Canare GS-6",   "connector_type": "TS\u2013TS"},
    "Tour Classic":        {"core_cable": "Canare GS-6",   "connector_type": "TS\u2013TS"},
    "Studio Vocal Classic": {"core_cable": "Canare L-4E6S", "connector_type": "XLR\u2013XLR"},
    "Tour Vocal Classic":  {"core_cable": "Canare L-4E6S", "connector_type": "XLR\u2013XLR"},
}


def _resolve_cable_attrs(connector_type: str, core_cable: str, series: str) -> Tuple[str, str]:
    """Resolve connector_type and core_cable, falling back to series defaults for MISC SKUs."""
    if connector_type and connector_type != "Varies" and core_cable and core_cable != "Varies":
        return connector_type, core_cable
    defaults = _SERIES_CABLE_DEFAULTS.get(series, {})
    resolved_connector = defaults.get("connector_type", connector_type) if (not connector_type or connector_type == "Varies") else connector_type
    resolved_cable = defaults.get("core_cable", core_cable) if (not core_cable or core_cable == "Varies") else core_cable
    return resolved_connector, resolved_cable


def _derive_cable_type(connector_type: str) -> str:
    """Map connector_type to Shopify metafield value (must match definition choices)."""
    normalized = (connector_type or "").replace("\u2013", "-").replace("\u2014", "-").upper()
    if "XLR" in normalized:
        return "Microphone Cable"
    return "Instrument Cable"


def _derive_series_metafield(series: str) -> str:
    """Map DB series name to Shopify metafield value (must match definition choices)."""
    s = (series or "").lower()
    if "studio" in s:
        return "Studio (Rayon)"
    if "tour" in s:
        return "Touring (Cotton)"
    return series  # fallback


def _set_product_metafields(product_id: str, length_ft: float, series: str, connector_type: str) -> bool:
    """Set cable metafields on a Shopify product using metafieldsSet.

    Sets custom.length (dimension), custom.series (text), custom.cable_type (text).
    Returns True on success.
    """
    cable_type = _derive_cable_type(connector_type)
    series_value = _derive_series_metafield(series)

    length_int = int(length_ft) if length_ft == int(length_ft) else length_ft
    length_value = f"{length_int} ft"

    metafields = [
        {
            "ownerId": product_id,
            "namespace": "custom",
            "key": "cable_length",
            "value": length_value,
            "type": "single_line_text_field",
        },
        {
            "ownerId": product_id,
            "namespace": "custom",
            "key": "series",
            "value": series_value,
            "type": "single_line_text_field",
        },
        {
            "ownerId": product_id,
            "namespace": "custom",
            "key": "cable_type",
            "value": cable_type,
            "type": "single_line_text_field",
        },
    ]

    try:
        session = get_shopify_session()
        mutation = """
        mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
            metafieldsSet(metafields: $metafields) {
                metafields { id namespace key value }
                userErrors { field message }
            }
        }
        """
        result = shopify.GraphQL().execute(mutation, variables={"metafields": metafields})
        data = json.loads(result)

        if "errors" in data:
            logger.error(f"GraphQL errors setting metafields: {data['errors']}")
            return False

        user_errors = data.get("data", {}).get("metafieldsSet", {}).get("userErrors", [])
        if user_errors:
            logger.error(f"User errors setting metafields: {user_errors}")
            return False

        logger.info(f"Set metafields on {product_id}: length={length_int}ft, series={series_value}, cable_type={cable_type}")
        return True
    except Exception as e:
        logger.error(f"Error setting metafields on {product_id}: {e}")
        return False
    finally:
        close_shopify_session()


def _find_variant_by_sku(shopify_sku: str) -> Optional[Dict[str, str]]:
    """Look up an existing product variant by SKU.

    Returns dict with variant_id, inventory_item_id, product_id or None.
    """
    try:
        session = get_shopify_session()
        query = """
        query findVariant($query: String!) {
            productVariants(first: 1, query: $query) {
                edges {
                    node {
                        id
                        inventoryItem { id }
                        product { id }
                    }
                }
            }
        }
        """
        variables = {"query": f"sku:{shopify_sku}"}
        result = shopify.GraphQL().execute(query, variables=variables)
        data = json.loads(result)

        if "errors" in data:
            logger.error(f"GraphQL errors finding variant for {shopify_sku}: {data['errors']}")
            return None

        edges = data.get("data", {}).get("productVariants", {}).get("edges", [])
        if not edges:
            return None

        node = edges[0]["node"]
        return {
            "variant_id": node["id"],
            "inventory_item_id": node["inventoryItem"]["id"],
            "product_id": node["product"]["id"],
        }
    except Exception as e:
        logger.error(f"Error finding variant for SKU {shopify_sku}: {e}")
        return None
    finally:
        close_shopify_session()


def _create_special_baby_product(title: str, shopify_sku: str, series: str, description: str = "", quantity: int = 1, weight_oz: Optional[float] = None, length_ft: Optional[float] = None, connector_type: str = "", cost: Optional[float] = None) -> Tuple[bool, Optional[str]]:
    """Create a new Shopify product for a special baby cable.

    Multi-step process:
      1. productSet to create product + variant (SKU, price, inventory tracking, weight)
      1b. publishablePublish to publish to all sales channels
      1c. metafieldsSet to set length/series/cable_type metafields
      2. inventorySetQuantities to set available quantity

    Returns (success, error_msg).
    """
    try:
        session = get_shopify_session()

        # Step 1: Create product with variant via productSet
        create_mutation = """
        mutation productSet($synchronous: Boolean!, $input: ProductSetInput!) {
            productSet(synchronous: $synchronous, input: $input) {
                product {
                    id
                    variants(first: 1) {
                        edges {
                            node {
                                id
                                inventoryItem { id }
                            }
                        }
                    }
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """
        # Build inventoryItem dict (tracking + optional weight + optional cost)
        inventory_item = {"tracked": True}
        if cost is not None:
            inventory_item["cost"] = cost
        if weight_oz is not None:
            inventory_item["measurement"] = {
                "weight": {"value": weight_oz, "unit": "OUNCES"}
            }

        product_input = {
            "title": title,
            "descriptionHtml": f"<p>{description}</p>" if description else "",
            "productType": SPECIAL_BABY_PRODUCT_TYPE,
            "category": AUDIO_VIDEO_CABLES_CATEGORY_ID,
            "tags": ["special-baby"],
            "status": "DRAFT",
            "productOptions": [{"name": "Title", "values": [{"name": "Default Title"}]}],
            "variants": [
                {
                    "sku": shopify_sku,
                    "price": SPECIAL_BABY_PRICE,
                    "optionValues": [{"optionName": "Title", "name": "Default Title"}],
                    "inventoryItem": inventory_item,
                }
            ],
        }
        variables = {"synchronous": True, "input": product_input}
        result = shopify.GraphQL().execute(create_mutation, variables=variables)
        data = json.loads(result)

        if "errors" in data:
            err = str(data["errors"])
            logger.error(f"GraphQL errors creating special baby product: {err}")
            return False, err

        create_data = data.get("data", {}).get("productSet", {})
        user_errors = create_data.get("userErrors", [])
        if user_errors:
            err = "; ".join(e["message"] for e in user_errors)
            logger.error(f"Shopify user errors creating special baby: {err}")
            return False, err

        product = create_data.get("product", {})
        product_id = product.get("id")
        variant_edges = product.get("variants", {}).get("edges", [])
        if not variant_edges:
            return False, "Product created but no variant returned"

        variant_node = variant_edges[0]["node"]
        inventory_item_id = variant_node["inventoryItem"]["id"]

        # Cache the inventory item for later increment calls
        _inventory_item_cache[shopify_sku] = inventory_item_id

        close_shopify_session()

        # Step 1b: Publish to all sales channels
        if product_id:
            _publish_product_to_all_channels(product_id)

        # Step 1c: Set metafields (length, series, cable_type)
        if product_id and length_ft and series and connector_type:
            _set_product_metafields(product_id, length_ft, series, connector_type)

        # Step 2: Set inventory quantity
        location_id = _get_location_id()
        if not location_id:
            return False, "Product created but could not determine location for inventory"

        session = get_shopify_session()
        set_mutation = """
        mutation inventorySetQuantities($input: InventorySetQuantitiesInput!) {
            inventorySetQuantities(input: $input) {
                userErrors { field message }
            }
        }
        """
        set_variables = {
            "input": {
                "reason": "correction",
                "name": "available",
                "ignoreCompareQuantity": True,
                "quantities": [
                    {
                        "inventoryItemId": inventory_item_id,
                        "locationId": location_id,
                        "quantity": quantity,
                    }
                ],
            }
        }
        result = shopify.GraphQL().execute(set_mutation, variables=set_variables)
        data = json.loads(result)

        if "errors" in data:
            logger.warning(f"Product created but inventory set failed: {data['errors']}")
            return True, None

        inv_errors = data.get("data", {}).get("inventorySetQuantities", {}).get("userErrors", [])
        if inv_errors:
            logger.warning(f"Product created but inventory user errors: {inv_errors}")

        logger.info(f"Created special baby product: {title} (SKU: {shopify_sku})")
        return True, None

    except Exception as e:
        err = str(e)
        logger.error(f"Error creating special baby product: {err}")
        return False, err
    finally:
        try:
            close_shopify_session()
        except Exception:
            pass


def update_special_baby_description(shopify_sku: str, description: str) -> Tuple[bool, Optional[str]]:
    """Update the description of an existing special baby Shopify product.

    Returns (success, error_msg).
    """
    try:
        variant_info = _find_variant_by_sku(shopify_sku)
        if not variant_info:
            return False, f"No Shopify product found for SKU {shopify_sku}"

        product_id = variant_info["product_id"]

        session = get_shopify_session()
        mutation = """
        mutation productUpdate($input: ProductInput!) {
            productUpdate(input: $input) {
                product { id }
                userErrors { field message }
            }
        }
        """
        variables = {
            "input": {
                "id": product_id,
                "descriptionHtml": f"<p>{description}</p>" if description else "",
            }
        }
        result = shopify.GraphQL().execute(mutation, variables=variables)
        data = json.loads(result)

        if "errors" in data:
            err = str(data["errors"])
            logger.error(f"GraphQL errors updating special baby description: {err}")
            return False, err

        user_errors = data.get("data", {}).get("productUpdate", {}).get("userErrors", [])
        if user_errors:
            err = "; ".join(e["message"] for e in user_errors)
            logger.error(f"Shopify user errors updating description: {err}")
            return False, err

        logger.info(f"Updated Shopify description for SKU {shopify_sku}")
        return True, None
    except Exception as e:
        err = str(e)
        logger.error(f"Error updating special baby description: {err}")
        return False, err
    finally:
        try:
            close_shopify_session()
        except Exception:
            pass


def ensure_special_baby_shopify_product(cable_record: Dict[str, Any], quantity: int = 1) -> Tuple[bool, Optional[str]]:
    """Find-or-create a Shopify product for a MISC (special baby) cable and set inventory.

    Uses the stable DB-sourced shopify_sku (from special_baby_types table).
    If a product with that SKU already exists, sets inventory to quantity.
    Otherwise creates a new product with the given inventory quantity.

    Returns (success, error_msg).
    """
    description = cable_record.get("description") or ""
    length = cable_record.get("length", "")
    series = cable_record.get("series", "")

    if not description:
        return False, "MISC cable has no description — cannot create Shopify product"

    # Use DB-sourced SKU from the joined special_baby_types table
    shopify_sku = cable_record.get("special_baby_shopify_sku")
    if not shopify_sku:
        return False, "MISC cable has no special_baby_shopify_sku — run migration or re-register"

    # Check if product already exists
    existing = _find_variant_by_sku(shopify_sku)
    if existing:
        # Product exists — set inventory to match Postgres
        return set_inventory_for_sku(shopify_sku, quantity)

    # Build title: "Special Baby | 10ft Tour Classic"
    length_str = ""
    if length:
        length_val = float(length)
        length_str = f"{int(length_val)}ft " if length_val == int(length_val) else f"{length_val}ft "

    series_display = _SERIES_DISPLAY.get(series.lower().replace(" ", "_"), series) if series else ""
    title_parts = ["Special Baby"]
    if length_str or series_display:
        title_parts.append(f"{length_str}{series_display}".strip())
    title = " - ".join(title_parts)

    # Resolve cable attrs (MISC SKUs have "Varies" — fall back to series defaults)
    raw_connector = cable_record.get("connector_type", "")
    raw_cable = cable_record.get("core_cable", "")
    connector_type, core_cable = _resolve_cable_attrs(raw_connector, raw_cable, series)

    # Calculate weight from component data
    weight_oz = None
    if length and connector_type and core_cable:
        weight_oz = _calculate_cable_weight_oz(float(length), connector_type, core_cable)

    # Calculate cost from YAML data
    from greenlight.product_lines import get_cost_for_special_baby
    cost = get_cost_for_special_baby(series, length) if series and length else None

    length_ft = float(length) if length else None
    return _create_special_baby_product(
        title, shopify_sku, series, description, quantity,
        weight_oz=weight_oz, length_ft=length_ft, connector_type=connector_type,
        cost=cost,
    )


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
