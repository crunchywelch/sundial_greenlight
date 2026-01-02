#!/bin/bash
# Deploy to production environment (greenlight.sundialwire.com)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"

cd "$APP_DIR"

echo "=== Deploying to PRODUCTION ==="
echo ""

# Safety check - confirm we're on main branch
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "main" ]; then
    echo "WARNING: You are on branch '$CURRENT_BRANCH', not 'main'"
    read -p "Are you sure you want to deploy to production? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Deployment cancelled."
        exit 1
    fi
fi

# Check for uncommitted changes
if [ -n "$(git status --porcelain)" ]; then
    echo "WARNING: You have uncommitted changes"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Deployment cancelled."
        exit 1
    fi
fi

# Build the app
echo "Building app..."
npx remix build

# Deploy Shopify config (extensions, scopes, etc.)
echo ""
echo "Deploying Shopify config..."
npx shopify app deploy --config shopify.app.toml --force

# Restart the production service
echo ""
echo "Restarting production service..."
sudo systemctl restart greenlight-shopify

# Wait for service to be ready, then reload nginx
echo ""
echo "Waiting for service to start..."
sleep 3
sudo systemctl reload nginx

# Check status
echo ""
echo "Service status:"
sudo systemctl status greenlight-shopify --no-pager

echo ""
echo "=== Production deployment complete ==="
echo "URL: https://greenlight.sundialwire.com"
