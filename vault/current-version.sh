#!/bin/sh
# Check for latest vault helm chart version

CURRENT_VERSION=$(grep 'version:' Chart.yaml | head -2 | tail -1 | sed 's/.*version: //')
LATEST_VERSION=$(curl -s https://raw.githubusercontent.com/hashicorp/vault-helm/main/Chart.yaml | grep '^version:' | sed 's/version: //')

echo "Current vault chart version: $CURRENT_VERSION"
echo "Latest vault chart version:  $LATEST_VERSION"

if [ "$CURRENT_VERSION" != "$LATEST_VERSION" ]; then
    echo ""
    echo "Update available!"
    echo "To update, run:"
    echo "  sed -i 's/version: $CURRENT_VERSION/version: $LATEST_VERSION/' Chart.yaml"
    echo "  helm dependency update"
fi
