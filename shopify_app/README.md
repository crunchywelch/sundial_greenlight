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
- `/app` - Main app page (currently shows Hello World via child route)
- `/app/_index.jsx` - The actual Hello World content
- `/auth/exit-iframe.jsx` - **Current entry point** - Shows Hello World in iframe
- `/auth/login.jsx` - Redirects to OAuth flow
- `/auth/callback.jsx` - OAuth callback handler
- `/auth.jsx` - Shopify OAuth redirect
- `/api/customer-cables.jsx` - API endpoint (ready to connect to PostgreSQL)

### App Architecture

**Current Flow:**
1. Shopify admin loads app in iframe
2. Requests hit `/` with `?shop=...` params
3. Redirects to `/app` preserving params
4. Currently shows "Hello World!" from `/app/_index.jsx`

**Auth Flow (for when needed):**
1. `/auth/login?shop=...` → `/auth?shop=...`
2. Redirects to Shopify OAuth
3. Callback to `/auth/callback`
4. Creates session and redirects to `/app`

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

## Next Steps

1. Replace Hello World content in `app/routes/auth.exit-iframe.jsx` with actual app UI
2. Connect `/api/customer-cables` endpoint to PostgreSQL database
3. Build customer cable display extension (in `extensions/` directory)
