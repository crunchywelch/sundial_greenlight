"""
Shopify API integration for customer lookup and order information
"""

import os
import shopify
from typing import Optional, Dict, Any
from dotenv import load_dotenv

load_dotenv()

# Shopify configuration from environment
SHOPIFY_SHOP_URL = os.getenv("SHOPIFY_SHOP_URL")  # e.g., "your-store.myshopify.com"
SHOPIFY_API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2024-01")
SHOPIFY_ACCESS_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN")  # For custom apps
SHOPIFY_PRIVATE_APP_PASSWORD = os.getenv("SHOPIFY_PRIVATE_APP_PASSWORD")  # For private apps


def get_shopify_session():
    """Create and return an active Shopify session"""
    if not SHOPIFY_SHOP_URL:
        raise ValueError("SHOPIFY_SHOP_URL not configured in .env file")

    # Use access token (custom app) or private app password
    token = SHOPIFY_ACCESS_TOKEN or SHOPIFY_PRIVATE_APP_PASSWORD
    if not token:
        raise ValueError("Either SHOPIFY_ACCESS_TOKEN or SHOPIFY_PRIVATE_APP_PASSWORD must be set in .env")

    session = shopify.Session(SHOPIFY_SHOP_URL, SHOPIFY_API_VERSION, token)
    shopify.ShopifyResource.activate_session(session)
    return session


def close_shopify_session():
    """Close the active Shopify session"""
    shopify.ShopifyResource.clear_session()


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
