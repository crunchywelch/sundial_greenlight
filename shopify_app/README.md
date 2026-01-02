# Greenlight Shopify App

A Shopify app for Greenlight cable management.

## Production Deployment

The app is deployed at **https://greenlight.sundialwire.com**

Access in Shopify admin: https://admin.shopify.com/store/sundial-audio-dev/apps/greenlight-2

### Production Server Management

**Service Control:**
```bash
# Restart the app
sudo systemctl restart greenlight-shopify

# Check status
sudo systemctl status greenlight-shopify

# View logs
sudo journalctl -u greenlight-shopify -f
```

**After Code Changes:**
```bash
cd /home/welch/projects/sundial_greenlight/shopify_app
npx remix build
sudo systemctl restart greenlight-shopify
```

### Key Configuration Files

**Systemd Service:** `/etc/systemd/system/greenlight-shopify.service`
- Contains environment variables (API key, secret, scopes)
- Runs the app on port 3000

**Nginx Configuration:**
- Reverse proxy from port 443 → 3000
- SSL configured for greenlight.sundialwire.com

**Environment:** `/home/welch/projects/sundial_greenlight/shopify_app/.env`
- SHOPIFY_API_KEY, SHOPIFY_API_SECRET, SHOPIFY_SCOPES
- Not used by systemd (vars are in service file)

### Important Routes

- `/` - Redirects to `/app` with query params preserved
- `/app` - Main app page with cable assignment UI
- `/app/_index.jsx` - Cable assignment interface (search customers, search cables, assign)
- `/app/settings` - Settings page
- `/auth/exit-iframe.jsx` - OAuth exit iframe handler
- `/auth/login.jsx` - Redirects to OAuth flow
- `/auth/callback.jsx` - OAuth callback handler
- `/auth.jsx` - Shopify OAuth redirect
- `/api/customer-cables.jsx` - API endpoint for fetching customer cables (connected to PostgreSQL)

### App Architecture

**Current Flow:**
1. Shopify admin loads app in iframe
2. Requests hit `/` with `?shop=...` params
3. Redirects to `/app` preserving params
4. Shows cable assignment UI from `/app/_index.jsx`

**Auth Flow:**
1. `/auth/login?shop=...` → `/auth?shop=...`
2. Redirects to Shopify OAuth
3. Callback to `/auth/callback`
4. Creates session and redirects to `/app`

**Cable Assignment Workflow:**
1. Search for customer by name, email, or phone
2. Search for cable by serial number or SKU
3. Select customer and cable from results
4. Click "Assign Cable to Customer" button
5. Updates `shopify_gid` field in `audio_cables` table

**Database Connection:**
- PostgreSQL database hosted on DigitalOcean
- Connection pool managed by `app/db.server.js`
- Credentials stored in systemd service environment variables
- Tables: `audio_cables`, `cable_skus`, `test_results`

### API Credentials

- **Client ID:** 57d05e5335f174afd0fc5e91b8e9f617
- **Client Secret:** Stored in systemd service environment
- **App URL:** https://greenlight.sundialwire.com

## Development

**Local Development:**
```bash
npm run dev
# or
shopify app dev
```

The Shopify CLI will:
- Start a local development server
- Create a tunnel URL (using Cloudflare)
- Open your app in the Shopify admin

## Features

### Cable Assignment ✅
- Search for Shopify customers by name, email, or phone
- Search for cables by serial number or SKU
- Assign cables to customers (updates database)
- Visual indicators for already-assigned cables

### Customer Cable API ✅
- Public API endpoint: `/api/customer-cables?customerId=<gid>`
- Returns all cables assigned to a customer
- Includes cable details, test results, and SKU information
- CORS-enabled for storefront access

## Next Steps

1. Build customer cable display extension (in `extensions/` directory)
2. Add cable unassignment functionality
3. Add bulk cable assignment
4. Add cable history/audit log
