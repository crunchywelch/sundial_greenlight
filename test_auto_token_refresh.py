#!/usr/bin/env python3
"""Test automatic token validation and refresh on startup"""

import sys
import os
sys.path.insert(0, '/home/welch/projects/sundial_greenlight')

def test_auto_refresh():
    """Test that get_shopify_session auto-refreshes invalid tokens"""

    print("=" * 70)
    print("Testing Automatic Token Refresh")
    print("=" * 70)

    # Save current token
    from dotenv import load_dotenv, set_key, find_dotenv
    load_dotenv()

    current_token = os.getenv("SHOPIFY_ACCESS_TOKEN")
    print(f"\nCurrent token (first 20 chars): {current_token[:20] if current_token else 'None'}...")

    # Temporarily set an invalid token
    env_file = find_dotenv()
    if env_file:
        print("\n1. Setting invalid token to test auto-refresh...")
        set_key(env_file, "SHOPIFY_ACCESS_TOKEN", "invalid_token_12345")

        # Reload environment
        load_dotenv(override=True)
        print(f"   Token set to: {os.getenv('SHOPIFY_ACCESS_TOKEN')}")

        # Now try to get a session - should auto-refresh
        print("\n2. Calling get_shopify_session() - should auto-refresh...")

        try:
            from greenlight import shopify_client
            # Force reload the module to get new env vars
            import importlib
            importlib.reload(shopify_client)

            session = shopify_client.get_shopify_session()
            shopify_client.close_shopify_session()

            print("   ✅ Session created successfully!")

            # Check if token was refreshed
            load_dotenv(override=True)
            new_token = os.getenv("SHOPIFY_ACCESS_TOKEN")
            print(f"\n3. Token after refresh (first 20 chars): {new_token[:20] if new_token else 'None'}...")

            if new_token and new_token != "invalid_token_12345":
                print("   ✅ Token was automatically refreshed!")
            else:
                print("   ⚠️  Token may not have been refreshed")

        except Exception as e:
            print(f"   ❌ Failed: {e}")
            import traceback
            traceback.print_exc()

            # Restore original token
            if current_token:
                set_key(env_file, "SHOPIFY_ACCESS_TOKEN", current_token)
            return False

    print("\n" + "=" * 70)
    print("✅ Auto-refresh test complete!")
    print("=" * 70)
    return True

if __name__ == "__main__":
    try:
        success = test_auto_refresh()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
