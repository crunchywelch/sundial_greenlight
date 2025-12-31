#!/usr/bin/env python3
"""Test Shopify API connection and customer search"""

import sys
sys.path.insert(0, '/home/welch/projects/sundial_greenlight')

from greenlight import shopify_client
import os

def test_shopify_connection():
    """Test Shopify API connection and credentials"""

    print("=" * 70)
    print("Shopify API Connection Test")
    print("=" * 70)

    # Check environment variables
    print("\n1. Checking environment variables:")
    print("-" * 70)

    shop_url = os.getenv("SHOPIFY_SHOP_URL")
    api_version = os.getenv("SHOPIFY_API_VERSION", "2024-01")
    access_token = os.getenv("SHOPIFY_ACCESS_TOKEN")
    client_id = os.getenv("SHOPIFY_CLIENT_ID")
    client_secret = os.getenv("SHOPIFY_CLIENT_SECRET")

    print(f"SHOPIFY_SHOP_URL: {shop_url if shop_url else '❌ NOT SET'}")
    print(f"SHOPIFY_API_VERSION: {api_version}")
    print(f"SHOPIFY_ACCESS_TOKEN: {'✅ SET' if access_token else '❌ NOT SET'}")
    print(f"SHOPIFY_CLIENT_ID: {'✅ SET' if client_id else '❌ NOT SET'}")
    print(f"SHOPIFY_CLIENT_SECRET: {'✅ SET' if client_secret else '❌ NOT SET'}")

    if not shop_url:
        print("\n❌ SHOPIFY_SHOP_URL is required but not set!")
        print("   Add to .env: SHOPIFY_SHOP_URL=your-store.myshopify.com")
        return False

    if not access_token and not (client_id and client_secret):
        print("\n❌ No authentication method configured!")
        print("   Need either SHOPIFY_ACCESS_TOKEN or SHOPIFY_CLIENT_ID+SHOPIFY_CLIENT_SECRET")
        return False

    # Test getting a session
    print("\n2. Testing Shopify session creation:")
    print("-" * 70)

    try:
        session = shopify_client.get_shopify_session()
        print("✅ Session created successfully")
        print(f"   Shop URL: {session.url}")
        print(f"   API Version: {session.api_version}")
        shopify_client.close_shopify_session()
    except Exception as e:
        print(f"❌ Failed to create session: {e}")
        return False

    # Test customer search with a simple query
    print("\n3. Testing customer search:")
    print("-" * 70)

    # Try searching for customers with a wildcard (should return some results if any exist)
    print("   Searching for all customers (limit 5)...")

    try:
        # Empty search or wildcard should return customers
        customers = shopify_client.search_customers_by_name("", limit=5)

        if customers:
            print(f"✅ Found {len(customers)} customer(s)")
            for i, customer in enumerate(customers[:3], 1):
                name = customer.get("displayName", "N/A")
                email = customer.get("email", "N/A")
                print(f"   {i}. {name} ({email})")
        else:
            print("⚠️  No customers found")
            print("   This could mean:")
            print("     - Store has no customers yet")
            print("     - API token doesn't have read_customers permission")
            print("     - Search query syntax issue")
    except Exception as e:
        print(f"❌ Customer search failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Test searching by a specific name
    print("\n4. Testing search by name:")
    print("-" * 70)

    search_name = input("Enter a customer name to search (or press Enter to skip): ").strip()

    if search_name:
        try:
            results = shopify_client.search_customers_by_name(search_name)

            if results:
                print(f"✅ Found {len(results)} result(s) for '{search_name}':")
                for i, customer in enumerate(results[:5], 1):
                    name = customer.get("displayName", "N/A")
                    email = customer.get("email", "N/A")
                    orders = customer.get("numberOfOrders", 0)
                    print(f"   {i}. {name} ({email}) - {orders} orders")
            else:
                print(f"⚠️  No results found for '{search_name}'")
        except Exception as e:
            print(f"❌ Search failed: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 70)
    print("✅ Shopify connection test complete!")
    print("=" * 70)

    return True

if __name__ == "__main__":
    try:
        success = test_shopify_connection()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
