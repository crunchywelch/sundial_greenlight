# Automatic Shopify Token Refresh

## Overview

The application now automatically validates and refreshes the Shopify access token on startup and during operation. Operators no longer need to manually run scripts when the token expires.

## How It Works

### On Application Startup

When you run `python -m greenlight.main`, the app:

1. **Checks Shopify Connection** - Validates the current access token
2. **Auto-Refreshes if Needed** - If token is invalid/expired, automatically gets a new one using client credentials
3. **Updates .env File** - Saves the new token for future sessions
4. **Continues Startup** - App starts normally, even if Shopify is unavailable

### During Operation

Any time a Shopify API call is made (customer search, assignment, etc.):

1. **Token Validation** - Checks if the current token is valid
2. **Auto-Refresh** - If invalid, automatically requests a new token
3. **Seamless Experience** - Operators never see token errors

## Startup Messages

### Success
```
🚀 Starting Greenlight Terminal...
🔗 Checking Shopify connection...
✅ Shopify connection OK
```

### Token Expired (Auto-Fixed)
```
🚀 Starting Greenlight Terminal...
🔗 Checking Shopify connection...
✅ Shopify connection OK
```
(Refresh happens silently in the background)

### Shopify Unavailable (Non-Blocking)
```
🚀 Starting Greenlight Terminal...
🔗 Checking Shopify connection...
⚠️  Shopify connection issue: [error details]
   Customer assignment features may not work
   Continuing startup...
```

## Requirements

For automatic token refresh to work, you need in `.env`:

```bash
SHOPIFY_SHOP_URL=your-store.myshopify.com
SHOPIFY_CLIENT_ID=your_client_id
SHOPIFY_CLIENT_SECRET=your_client_secret
```

The `SHOPIFY_ACCESS_TOKEN` is automatically managed - no need to update it manually.

## Technical Details

### Files Modified

1. **greenlight/shopify_client.py**
   - Added `validate_token()` function
   - Modified `get_shopify_session()` to auto-validate and refresh
   - Auto-reloads environment after token refresh

2. **greenlight/main.py**
   - Added `check_shopify_connection()` function
   - Called on startup before UI loads
   - Non-blocking - app starts even if Shopify fails

### Token Validation

The system validates tokens by making a lightweight GraphQL query:
```graphql
{ shop { name } }
```

If this returns a 401 Unauthorized error, the token is considered invalid and refreshed.

### Error Handling

- **Token refresh fails**: App warns but continues
- **Client credentials missing**: App warns but continues
- **Shopify API down**: App warns but continues
- **Network issues**: App warns but continues

The app is designed to be resilient - Shopify features gracefully degrade if unavailable.

## Manual Refresh (Optional)

If you ever need to manually refresh the token:

```bash
source dev_env.sh
python refresh_shopify_token.py
```

But this should rarely be necessary - the automatic refresh handles it.

## Troubleshooting

### "Invalid API key or access token"

This should automatically fix itself. If it doesn't:

1. Check that `SHOPIFY_CLIENT_ID` and `SHOPIFY_CLIENT_SECRET` are correct in `.env`
2. Verify the app has admin API access in Shopify
3. Run `python refresh_shopify_token.py` manually

### Customer Search Returns No Results

If Shopify connection is OK but search returns nothing:

1. Verify customers exist in your Shopify store
2. Check API permissions include `read_customers` scope
3. Try searching with a specific customer name

### Connection Check Hangs

If startup check takes too long:

- Network connectivity to Shopify may be slow
- App will continue after a reasonable timeout
- Shopify features may be unavailable until connection stabilizes

## Benefits

✅ **No Manual Intervention** - Operators never need to run scripts
✅ **Seamless Operation** - Token expiration handled transparently
✅ **Resilient** - App works even when Shopify is down
✅ **Automatic Updates** - Token automatically saved for next session
✅ **Clear Feedback** - Startup messages show connection status
