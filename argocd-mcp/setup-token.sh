#!/bin/bash
# Setup script for ArgoCD MCP API token
# This script generates an API token for the 'claude' account and stores it in Vault

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}ArgoCD MCP Token Setup${NC}"
echo "========================================"

# Check prerequisites
echo -e "\n${YELLOW}Checking prerequisites...${NC}"

if ! command -v argocd &> /dev/null; then
    echo -e "${RED}Error: argocd CLI not found${NC}"
    echo "Install it from: https://argo-cd.readthedocs.io/en/stable/cli_installation/"
    exit 1
fi

if ! command -v vault &> /dev/null; then
    echo -e "${RED}Error: vault CLI not found${NC}"
    echo "Install it from: https://developer.hashicorp.com/vault/install"
    exit 1
fi

# Check if logged into ArgoCD
if ! argocd account get-user-info &> /dev/null; then
    echo -e "${RED}Error: Not logged into ArgoCD${NC}"
    echo "Run: argocd login argocd.lan"
    exit 1
fi

# Check if the claude account exists
echo -e "\n${YELLOW}Checking claude account...${NC}"
if ! argocd account list | grep -q "claude"; then
    echo -e "${RED}Error: 'claude' account not found${NC}"
    echo "Make sure argocd/values.yaml has been synced with the claude account config:"
    echo "  argocd app sync argocd"
    exit 1
fi

echo -e "${GREEN}Found claude account${NC}"

# Show current account settings
echo -e "\n${YELLOW}Account details:${NC}"
argocd account get --account claude

# Generate API token
echo -e "\n${YELLOW}Generating API token...${NC}"
TOKEN=$(argocd account generate-token --account claude)

if [ -z "$TOKEN" ]; then
    echo -e "${RED}Error: Failed to generate token${NC}"
    exit 1
fi

echo -e "${GREEN}Token generated successfully${NC}"

# Store in Vault
echo -e "\n${YELLOW}Storing token in Vault...${NC}"

# Check Vault connection
if ! vault status &> /dev/null; then
    echo -e "${RED}Error: Cannot connect to Vault${NC}"
    echo "Make sure VAULT_ADDR is set and you're authenticated"
    echo "  export VAULT_ADDR=http://vault.lan:8200"
    echo "  vault login"
    exit 1
fi

vault kv put kv/argocd-mcp/token ARGOCD_API_TOKEN="$TOKEN"

echo -e "${GREEN}Token stored in Vault at kv/argocd-mcp/token${NC}"

# Verify
echo -e "\n${YELLOW}Verifying Vault secret...${NC}"
if vault kv get kv/argocd-mcp/token &> /dev/null; then
    echo -e "${GREEN}Vault secret verified${NC}"
else
    echo -e "${RED}Warning: Could not verify Vault secret${NC}"
fi

echo -e "\n${GREEN}Setup complete!${NC}"
echo ""
echo "Next steps:"
echo "  1. Sync the argocd-mcp application:"
echo "     argocd app sync argocd-mcp"
echo ""
echo "  2. Sync mcp-gateway to register the new server:"
echo "     argocd app sync mcp-gateway"
echo ""
echo "  3. Verify the pod is running:"
echo "     kubectl get pods -n argocd-mcp"
