#!/bin/sh
# Check current and latest Ollama versions

# Check for required dependencies
if ! command -v jq >/dev/null 2>&1; then
    echo "Error: jq is required but not installed."
    echo "Install with: sudo apt install jq"
    exit 1
fi

echo "=== Ollama Version Check ==="
echo ""

# Get current version from values.yaml
CURRENT_VERSION=$(grep 'tag:' values.yaml | head -1 | sed 's/.*tag:[[:space:]]*//' | tr -d '"')
echo "Current Ollama version: $CURRENT_VERSION"

echo ""
echo "=== Latest Version Check ==="

# Get latest version from Docker Hub (numbered version, not 'latest')
echo "Checking Docker Hub for latest ollama image..."
LATEST_TAG=$(curl -s "https://hub.docker.com/v2/repositories/ollama/ollama/tags?page_size=20&ordering=last_updated" | \
    jq -r '.results[].name' | \
    grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | \
    head -1)

if [ -z "$LATEST_TAG" ]; then
    echo "Failed to fetch latest version from Docker Hub"
    echo "Check manually at: https://hub.docker.com/r/ollama/ollama/tags"
    exit 1
fi

echo "Latest Ollama version: $LATEST_TAG"

# Compare versions
if [ "$CURRENT_VERSION" = "$LATEST_TAG" ]; then
    echo ""
    echo "✓ You are running the latest version!"
else
    echo ""
    echo "⚠ UPDATE AVAILABLE!"
    echo ""
    echo "To update:"
    echo "  1. Update values.yaml image version:"
    echo "     sed -i 's|tag: \"$CURRENT_VERSION\"|tag: \"$LATEST_TAG\"|' values.yaml"
    echo ""
    echo "  2. Update Chart.yaml appVersion:"
    echo "     sed -i 's|appVersion: \"$CURRENT_VERSION\"|appVersion: \"$LATEST_TAG\"|' Chart.yaml"
    echo ""
    echo "  3. Commit and push:"
    echo "     git add values.yaml Chart.yaml"
    echo "     git commit -m 'Update Ollama to $LATEST_TAG'"
    echo "     git push"
fi

echo ""
echo "For release notes, visit:"
echo "  https://github.com/ollama/ollama/releases"
