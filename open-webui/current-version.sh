#!/bin/sh
# Check current and latest Open WebUI versions

# Check for required dependencies
if ! command -v jq >/dev/null 2>&1; then
    echo "Error: jq is required but not installed."
    echo "Install with: sudo apt install jq"
    exit 1
fi

echo "=== Open WebUI Version Check ==="
echo ""

# Get current version from values.yaml
CURRENT_VERSION=$(grep 'tag:' values.yaml | head -1 | sed 's/.*tag:[[:space:]]*//' | tr -d '"')
echo "Current Open WebUI version: $CURRENT_VERSION"

echo ""
echo "=== Latest Version Check ==="

# Get latest version from GitHub releases
echo "Checking GitHub for latest Open WebUI release..."
LATEST_VERSION=$(curl -s "https://api.github.com/repos/open-webui/open-webui/releases/latest" | \
    jq -r '.tag_name')

if [ -z "$LATEST_VERSION" ] || [ "$LATEST_VERSION" = "null" ]; then
    echo "Failed to fetch latest version from GitHub"
    echo "Check manually at: https://github.com/open-webui/open-webui/releases"
    exit 1
fi

echo "Latest Open WebUI version: $LATEST_VERSION"

# Compare versions
if [ "$CURRENT_VERSION" = "$LATEST_VERSION" ]; then
    echo ""
    echo "✓ You are running the latest version!"
else
    echo ""
    echo "⚠ UPDATE AVAILABLE!"
    echo ""
    echo "To update:"
    echo "  1. Update values.yaml image version:"
    echo "     sed -i 's|tag: \"$CURRENT_VERSION\"|tag: \"$LATEST_VERSION\"|' values.yaml"
    echo ""
    echo "  2. Update Chart.yaml appVersion:"
    echo "     sed -i 's|appVersion: \"${CURRENT_VERSION#v}\"|appVersion: \"${LATEST_VERSION#v}\"|' Chart.yaml"
    echo ""
    echo "  3. Commit and push:"
    echo "     git add values.yaml Chart.yaml"
    echo "     git commit -m 'Update Open WebUI to $LATEST_VERSION'"
    echo "     git push"
fi

echo ""
echo "For release notes, visit:"
echo "  https://github.com/open-webui/open-webui/releases"
