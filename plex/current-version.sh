#!/bin/sh
# Check current and latest Plex Media Server versions

# Check for required dependencies
if ! command -v jq >/dev/null 2>&1; then
    echo "Error: jq is required but not installed."
    echo "Install with: sudo apt install jq"
    exit 1
fi

echo "=== Plex Media Server Version Check ==="
echo ""

# Get current version from values.yaml (simple-service format)
CURRENT_VERSION=$(grep '^\s*tag:' values.yaml | head -1 | sed 's/.*tag:[[:space:]]*//' | tr -d '"')
echo "Current Plex version: $CURRENT_VERSION"

echo ""
echo "=== Latest Version Check ==="

# Get latest version from Docker Hub (numbered version, not 'latest')
echo "Checking Docker Hub for latest pms-docker image..."
LATEST_TAG=$(curl -s "https://registry.hub.docker.com/v2/repositories/plexinc/pms-docker/tags?page_size=100" | \
    jq -r '.results[] | select(.name | test("^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+-[0-9a-f]+$")) | .name' | \
    head -1)

if [ -z "$LATEST_TAG" ]; then
    echo "Failed to fetch latest version from Docker Hub"
    echo "Check manually at: https://hub.docker.com/r/plexinc/pms-docker/tags"
    exit 1
fi

echo "Latest Plex version: $LATEST_TAG"

# Compare versions
if [ "$CURRENT_VERSION" = "$LATEST_TAG" ]; then
    echo ""
    echo "✓ You are running the latest version!"
else
    echo ""
    echo "⚠ UPDATE AVAILABLE!"
    echo ""
    echo "To update:"
    echo "  1. Update values.yaml image tag:"
    echo "     sed -i 's|tag: \"$CURRENT_VERSION\"|tag: \"$LATEST_TAG\"|' values.yaml"
    echo ""
    echo "  2. Commit and push:"
    echo "     git add values.yaml"
    echo "     git commit -m 'Update Plex Media Server to $LATEST_TAG'"
    echo "     git push"
fi

echo ""
echo "For release notes, visit:"
echo "  https://forums.plex.tv/t/plex-media-server/30447"
