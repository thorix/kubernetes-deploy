#!/bin/sh
# Check current and latest cloudflared versions
# NOTE: Cloudflare recommends running the latest version for security and compatibility

echo "=== Cloudflared Version Check ==="
echo ""

# Get current chart version
CHART_VERSION=$(grep 'version:' Chart.yaml | head -1 | sed 's/.*version: //')
echo "Chart version: $CHART_VERSION"

# Get current appVersion (cloudflared version)
CURRENT_VERSION=$(grep 'appVersion:' Chart.yaml | sed 's/.*appVersion: "\(.*\)".*/\1/')
echo "Current cloudflared version: $CURRENT_VERSION"

# Get image tag from values
IMAGE_TAG=$(grep '^\s*tag:' values.yaml | head -1 | sed -E 's/.*tag:\s*"([^"]+)".*/\1/')
echo "Image tag (values.yaml): $IMAGE_TAG"

echo ""
echo "=== Latest Version Check ==="

# Get latest release from GitHub
LATEST_VERSION=$(curl -s https://api.github.com/repos/cloudflare/cloudflared/releases/latest | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/')

if [ -z "$LATEST_VERSION" ]; then
    echo "Failed to fetch latest version from GitHub"
    echo "Check manually at: https://github.com/cloudflare/cloudflared/releases"
    exit 1
fi

echo "Latest cloudflared version: $LATEST_VERSION"

# Compare versions
if [ "$CURRENT_VERSION" = "$LATEST_VERSION" ]; then
    echo ""
    echo "✓ You are running the latest version!"
else
    echo ""
    echo "⚠ UPDATE AVAILABLE!"
    echo ""
    echo "Cloudflare recommends running the latest version for:"
    echo "  - Security updates"
    echo "  - Bug fixes"
    echo "  - Compatibility with Cloudflare's edge network"
    echo ""
    echo "To update:"
    echo "  1. Update Chart.yaml:"
    echo "     sed -i 's/appVersion: \"$CURRENT_VERSION\"/appVersion: \"$LATEST_VERSION\"/' Chart.yaml"
    echo ""
    echo "  2. Update values.yaml:"
    echo "     sed -i 's/tag: \"$IMAGE_TAG\"/tag: \"$LATEST_VERSION\"/' values.yaml"
    echo ""
    echo "  3. Commit and push:"
    echo "     git add Chart.yaml values.yaml"
    echo "     git commit -m 'Update cloudflared to $LATEST_VERSION'"
    echo "     git push"
fi

echo ""
echo "For release notes, visit:"
echo "  https://github.com/cloudflare/cloudflared/releases/tag/$LATEST_VERSION"
