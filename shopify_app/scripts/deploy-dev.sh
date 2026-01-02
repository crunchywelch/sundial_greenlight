#!/bin/bash
# Deploy to development environment (greenlightdev.sundialwire.com)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"

cd "$APP_DIR"

echo "=== Deploying to DEVELOPMENT ==="
echo ""

# Build the app
echo "Building app..."
npx remix build

# Deploy Shopify config (extensions, scopes, etc.)
echo ""
echo "Deploying Shopify config..."
npx shopify app deploy --config shopify.app.greenlight-dev.toml --force

# Restart the dev service
echo ""
echo "Restarting dev service..."
sudo systemctl restart greenlight-shopify-dev

# Check status
echo ""
echo "Service status:"
sudo systemctl status greenlight-shopify-dev --no-pager

echo ""
echo "=== Development deployment complete ==="
echo "URL: https://greenlightdev.sundialwire.com"
