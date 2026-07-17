#!/bin/sh
# Check for latest Longhorn helm chart version

CURRENT_VERSION=$(grep 'version:' Chart.yaml | head -2 | tail -1 | sed 's/.*version: //')
LATEST_VERSION=$(curl -s https://api.github.com/repos/longhorn/longhorn/releases/latest | grep '"tag_name":' | sed -E 's/.*"v([^"]+)".*/\1/')

echo "Current Longhorn chart version: $CURRENT_VERSION"
echo "Latest Longhorn chart version:  $LATEST_VERSION"

if [ "$CURRENT_VERSION" != "$LATEST_VERSION" ]; then
    echo ""
    echo "Update available!"
    echo "To update, run:"
    echo "  sed -i 's/version: $CURRENT_VERSION/version: $LATEST_VERSION/' Chart.yaml"
    echo "  sed -i 's/appVersion: \".*\"/appVersion: \"$LATEST_VERSION\"/' Chart.yaml"
    echo "  helm dependency update"
fi
