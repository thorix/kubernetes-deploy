#!/bin/sh
# Check current and latest Vault Secrets Operator versions

echo "=== Vault Secrets Operator Version Check ==="
echo ""

# Get current chart version
CHART_VERSION=$(grep 'version:' Chart.yaml | head -1 | sed 's/.*version: //')
echo "Chart version: $CHART_VERSION"

# Get current VSO dependency version
VSO_VERSION=$(grep -A 2 'name: vault-secrets-operator' Chart.yaml | grep 'version:' | sed 's/.*version: //')
echo "Current Vault Secrets Operator version: $VSO_VERSION"

echo ""
echo "=== Latest Version Check ==="

# Get latest release from GitHub
LATEST_VERSION=$(curl -s https://api.github.com/repos/hashicorp/vault-secrets-operator/releases/latest | grep '\"tag_name\":' | sed -E 's/.*"v([^"]+)".*/\1/')

if [ -z "$LATEST_VERSION" ]; then
    echo "Failed to fetch latest version from GitHub"
    echo "Check manually at: https://github.com/hashicorp/vault-secrets-operator/releases"
    exit 1
fi

echo "Latest Vault Secrets Operator version: $LATEST_VERSION"

# Compare versions
if [ "$VSO_VERSION" = "$LATEST_VERSION" ]; then
    echo ""
    echo "✓ You are running the latest version!"
else
    echo ""
    echo "⚠ UPDATE AVAILABLE!"
    echo ""
    echo "To update:"
    echo "  1. Update Chart.yaml dependency version:"
    echo "     sed -i '/name: vault-secrets-operator/,/version:/ s/version: .*/version: $LATEST_VERSION/' Chart.yaml"
    echo ""
    echo "  2. Update Helm dependencies:"
    echo "     helm dependency update"
    echo ""
    echo "  3. Commit and push:"
    echo "     git add Chart.yaml Chart.lock"
    echo "     git commit -m 'Update Vault Secrets Operator to $LATEST_VERSION'"
    echo "     git push"
fi

echo ""
echo "For release notes, visit:"
echo "  https://github.com/hashicorp/vault-secrets-operator/releases/tag/v$LATEST_VERSION"
