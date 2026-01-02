#!/bin/bash
# Check status of both environments

echo "=== Greenlight Shopify App Status ==="
echo ""

echo "--- PRODUCTION (port 3000) ---"
sudo systemctl status greenlight-shopify --no-pager -l 2>/dev/null || echo "Service not found"

echo ""
echo "--- DEVELOPMENT (port 3001) ---"
sudo systemctl status greenlight-shopify-dev --no-pager -l 2>/dev/null || echo "Service not found"

echo ""
echo "--- Port Status ---"
ss -tlnp | grep -E ':(3000|3001)' || echo "No services listening on 3000 or 3001"
