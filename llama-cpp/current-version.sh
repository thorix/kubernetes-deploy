#!/bin/sh
# Check llama.cpp release information
#
# Note: The llama.cpp Docker images use rolling tags (full-vulkan, full-cuda, full)
# rather than versioned tags. To update, simply restart the deployment to pull
# the latest image.

echo "=== llama.cpp Version Check ==="
echo ""

# Get current tag from values.yaml
CURRENT_TAG=$(grep 'tag:' values.yaml | head -1 | sed 's/.*tag:[[:space:]]*//' | tr -d '"')
echo "Current image tag: $CURRENT_TAG"
echo ""
echo "Note: llama.cpp uses rolling tags (not versioned)."
echo "The image is updated by restarting the deployment."

echo ""
echo "=== Latest GitHub Release ==="

# Check for required dependencies
if command -v jq >/dev/null 2>&1; then
    LATEST_RELEASE=$(curl -s "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest" | jq -r '.tag_name')
    if [ -n "$LATEST_RELEASE" ] && [ "$LATEST_RELEASE" != "null" ]; then
        echo "Latest llama.cpp release: $LATEST_RELEASE"
    else
        echo "Could not fetch latest release"
    fi
else
    echo "Install jq to check latest release: sudo apt install jq"
fi

echo ""
echo "To update to latest image:"
echo "  kubectl rollout restart deployment/llama-cpp -n llama"
echo ""
echo "For release notes, visit:"
echo "  https://github.com/ggml-org/llama.cpp/releases"
