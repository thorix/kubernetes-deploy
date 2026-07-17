#!/bin/sh

# Get the latest external-dns version from GitHub releases
# External DNS releases are tagged as v0.x.y
echo "Fetching latest external-dns version from GitHub..."
LATEST_VERSION=$(curl -s https://api.github.com/repos/kubernetes-sigs/external-dns/releases/latest | grep '"tag_name":' | sed -E 's/.*"v([^"]+)".*/\1/')

if [ -z "$LATEST_VERSION" ]; then
    echo "Error: Could not fetch latest version"
    exit 1
fi

echo "Latest external-dns version: v${LATEST_VERSION}"

# Check current version in Chart.yaml
CURRENT_VERSION=$(grep '^appVersion:' Chart.yaml | sed -E 's/appVersion: "?([^"]+)"?/\1/')
echo "Current version in Chart.yaml: ${CURRENT_VERSION}"

# Compare versions
if [ "$CURRENT_VERSION" = "$LATEST_VERSION" ]; then
    echo "✓ Chart is up to date!"
else
    echo "⚠ Update available: ${CURRENT_VERSION} -> ${LATEST_VERSION}"
    echo ""
    echo "To update, run:"
    echo "  sed -i 's/appVersion: \"${CURRENT_VERSION}\"/appVersion: \"${LATEST_VERSION}\"/' Chart.yaml"
    echo "  sed -i 's/tag: v${CURRENT_VERSION}/tag: v${LATEST_VERSION}/' values.yaml"
fi
