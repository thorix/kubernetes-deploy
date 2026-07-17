#!/bin/sh
# Check current and latest SMB CSI Driver versions

echo "=== SMB CSI Driver Version Check ==="
echo ""

# Get current chart version
CHART_VERSION=$(grep 'version:' Chart.yaml | head -1 | sed 's/.*version: //')
echo "Chart version: $CHART_VERSION"

# Get current SMB CSI Driver dependency version
SMB_VERSION=$(grep -A 2 'name: csi-driver-smb' Chart.yaml | grep 'version:' | sed 's/.*version: //')
echo "Current SMB CSI Driver version: $SMB_VERSION"

echo ""
echo "=== Latest Version Check ==="

# Get latest release from GitHub
LATEST_VERSION=$(curl -s https://api.github.com/repos/kubernetes-csi/csi-driver-smb/releases/latest | grep '\"tag_name\":' | sed -E 's/.*"([^"]+)".*/\1/')

if [ -z "$LATEST_VERSION" ]; then
    echo "Failed to fetch latest version from GitHub"
    echo "Check manually at: https://github.com/kubernetes-csi/csi-driver-smb/releases"
    exit 1
fi

echo "Latest SMB CSI Driver version: $LATEST_VERSION"

# Compare versions
if [ "$SMB_VERSION" = "$LATEST_VERSION" ]; then
    echo ""
    echo "✓ You are running the latest version!"
else
    echo ""
    echo "⚠ UPDATE AVAILABLE!"
    echo ""
    echo "To update:"
    echo "  1. Update Chart.yaml dependency version:"
    echo "     sed -i '/name: csi-driver-smb/,/version:/ s/version: .*/version: $LATEST_VERSION/' Chart.yaml"
    echo ""
    echo "  2. Update Helm dependencies:"
    echo "     helm dependency update"
    echo ""
    echo "  3. Commit and push:"
    echo "     git add Chart.yaml Chart.lock"
    echo "     git commit -m 'Update SMB CSI Driver to $LATEST_VERSION'"
    echo "     git push"
fi

echo ""
echo "For release notes, visit:"
echo "  https://github.com/kubernetes-csi/csi-driver-smb/releases/tag/$LATEST_VERSION"
