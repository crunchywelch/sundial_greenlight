# Greenlight Shopify App

A simple Shopify app for Greenlight cable management.

## Setup

1. Install dependencies (already done):
   ```bash
   npm install
   ```

2. Start the development server:
   ```bash
   npm run dev
   # or
   shopify app dev
   ```

3. The Shopify CLI will:
   - Start a local development server
   - Create a tunnel URL (using Cloudflare)
   - Open your app in the Shopify admin

## Routes

- `/app` - Main app page
- `/app/settings` - Settings page (Hello World!)

## How to Access the Settings Page

Once you run `shopify app dev`:
1. The CLI will open your Shopify store admin
2. Navigate to Apps > Greenlight
3. Click on the app to see the main page
4. Navigate to `/app/settings` to see your Hello World settings page

Alternatively, in the Shopify admin, you can directly access:
- Your App → Settings (if configured in app navigation)
