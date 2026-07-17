#!/usr/bin/env bash
# setup-token.sh — Create a Grafana service account and store the token in Vault
#
# Prerequisites:
#   - VAULT_ADDR and VAULT_TOKEN set
#   - Grafana admin credentials (uses default admin/admin or set GRAFANA_ADMIN_PASSWORD)
#
# Usage: ./setup-token.sh

set -euo pipefail

GRAFANA_URL="${GRAFANA_URL:-https://grafana.lan}"
GRAFANA_ADMIN_USER="${GRAFANA_ADMIN_USER:-admin}"
GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-}"

if [[ -z "$GRAFANA_ADMIN_PASSWORD" ]]; then
    echo "Enter Grafana admin password:"
    read -rs GRAFANA_ADMIN_PASSWORD
fi

SA_NAME="mcp-grafana"

echo "Creating service account '$SA_NAME' in Grafana..."

# Create service account (Editor role for broad read + query access)
SA_RESPONSE=$(curl -sf -X POST "$GRAFANA_URL/api/serviceaccounts" \
  -u "$GRAFANA_ADMIN_USER:$GRAFANA_ADMIN_PASSWORD" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"$SA_NAME\", \"role\": \"Editor\"}" 2>&1) || {
    echo "Service account may already exist, trying to find it..."
    SA_RESPONSE=$(curl -sf "$GRAFANA_URL/api/serviceaccounts/search?query=$SA_NAME" \
      -u "$GRAFANA_ADMIN_USER:$GRAFANA_ADMIN_PASSWORD")
}

SA_ID=$(echo "$SA_RESPONSE" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
if [[ -z "$SA_ID" ]]; then
    echo "ERROR: Could not get service account ID"
    echo "Response: $SA_RESPONSE"
    exit 1
fi
echo "  Service account ID: $SA_ID"

echo "Creating token..."
TOKEN_RESPONSE=$(curl -sf -X POST "$GRAFANA_URL/api/serviceaccounts/$SA_ID/tokens" \
  -u "$GRAFANA_ADMIN_USER:$GRAFANA_ADMIN_PASSWORD" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"mcp-token-$(date +%s)\"}")

TOKEN=$(echo "$TOKEN_RESPONSE" | grep -o '"key":"[^"]*"' | cut -d'"' -f4)
if [[ -z "$TOKEN" ]]; then
    echo "ERROR: Could not extract token"
    echo "Response: $TOKEN_RESPONSE"
    exit 1
fi
echo "  Token created (starts with: ${TOKEN:0:10}...)"

echo "Writing token to Vault at kv/grafana-mcp/token..."
vault kv put kv/grafana-mcp/token GRAFANA_SERVICE_ACCOUNT_TOKEN="$TOKEN"
echo "Done!"

echo ""
echo "Next steps:"
echo "  1. Deploy: git push (ArgoCD syncs grafana-mcp)"
echo "  2. Verify: kubectl logs -n grafana-mcp deploy/grafana-mcp-simple-service"
echo "  3. Re-register MCP gateway servers: argocd app sync mcp-gateway"
