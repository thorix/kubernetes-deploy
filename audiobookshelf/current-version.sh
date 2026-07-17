#!/bin/sh
# Check current and latest Audiobookshelf versions

echo "=== Audiobookshelf Version Check ==="
echo ""

# Get current version from values.yaml
CURRENT_VERSION=$(grep 'image: ghcr.io/advplyr/audiobookshelf:' values.yaml | sed 's/.*audiobookshelf://' | sed 's/^[ \t]*//')
echo "Current Audiobookshelf version: $CURRENT_VERSION"

echo ""
echo "=== Latest Version Check ==="

# Get latest version from GitHub releases
echo "Checking GitHub for latest release..."
LATEST_VERSION=$(curl -s https://api.github.com/repos/advplyr/audiobookshelf/releases/latest | jq -r '.tag_name' | sed 's/^v//')

if [ -z "$LATEST_VERSION" ]; then
    echo "Failed to fetch latest version from GitHub"
    echo "Check manually at: https://github.com/advplyr/audiobookshelf/releases"
    exit 1
fi

echo "Latest Audiobookshelf version: $LATEST_VERSION"

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
    echo "     sed -i 's|image: ghcr.io/advplyr/audiobookshelf:.*|image: ghcr.io/advplyr/audiobookshelf:$LATEST_VERSION|' values.yaml"
    echo ""
    echo "  2. Commit and push:"
    echo "     git add values.yaml"
    echo "     git commit -m 'Update Audiobookshelf to $LATEST_VERSION'"
    echo "     git push"
fi

echo ""
echo "For release notes, visit:"
echo "  https://github.com/advplyr/audiobookshelf/releases/latest"
