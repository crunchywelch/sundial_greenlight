#!/bin/bash
# View logs for dev or prod environment

ENV=${1:-dev}

case "$ENV" in
    dev|development)
        echo "=== Development Logs ==="
        sudo journalctl -u greenlight-shopify-dev -f
        ;;
    prod|production)
        echo "=== Production Logs ==="
        sudo journalctl -u greenlight-shopify -f
        ;;
    *)
        echo "Usage: $0 [dev|prod]"
        echo "  dev  - View development logs (default)"
        echo "  prod - View production logs"
        exit 1
        ;;
esac
