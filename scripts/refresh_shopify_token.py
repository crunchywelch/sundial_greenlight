#!/usr/bin/env python3
"""Refresh Shopify access token using client credentials"""

import sys
sys.path.insert(0, '/home/welch/projects/sundial_greenlight')

from greenlight.shopify_client import get_access_token_from_client_credentials
import os

def refresh_token():
    """Get a fresh access token from Shopify"""

    print("=" * 70)
    print("Refreshing Shopify Access Token")
    print("=" * 70)

    shop_url = os.getenv("SHOPIFY_SHOP_URL")
    client_id = os.getenv("SHOPIFY_CLIENT_ID")
    client_secret = os.getenv("SHOPIFY_CLIENT_SECRET")

    print(f"\nShop: {shop_url}")
    print(f"Client ID: {client_id[:10]}..." if client_id else "Client ID: NOT SET")

    if not shop_url or not client_id or not client_secret:
        print("\n❌ Missing required credentials!")
        print("Need: SHOPIFY_SHOP_URL, SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET")
        return False

    print("\nRequesting new access token from Shopify...")

    try:
        token = get_access_token_from_client_credentials()

        if token:
            print(f"\n✅ Successfully obtained new access token!")
            print(f"   Token (first 20 chars): {token[:20]}...")
            print(f"\n   Token has been saved to .env file")
            print(f"   You can now use the customer search!")
            return True
        else:
            print(f"\n❌ Failed to obtain access token")
            print(f"   Check your CLIENT_ID and CLIENT_SECRET")
            return False

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    try:
        success = refresh_token()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Failed: {e}")
        sys.exit(1)
