#!/bin/sh
# Check current and available ComfyUI Docker image tags

echo "=== ComfyUI Version Check ==="
echo ""

# Get current chart version
CHART_VERSION=$(grep 'version:' Chart.yaml | head -1 | sed 's/.*version: //')
echo "Chart version: $CHART_VERSION"

# Get current image tag from base values
BASE_IMAGE_TAG=$(grep '^\s*tag:' values.yaml | head -1 | sed -E 's/.*tag:\s*"([^"]+)".*/\1/')
echo "Base image tag (values.yaml): $BASE_IMAGE_TAG"

# Get production image tag
PROD_IMAGE_TAG=$(grep '^\s*tag:' values.prod.yaml | head -1 | sed -E 's/.*tag:\s*"([^"]+)".*/\1/')
echo "Production image tag (values.prod.yaml): $PROD_IMAGE_TAG"

echo ""
echo "=== Available Tags on Docker Hub ==="
echo "Checking yanwk/comfyui-boot..."

# Fetch popular tags from Docker Hub
# Note: Docker Hub API v2 requires authentication for full tag list
# We'll check specific known tags
for TAG in "rocm" "cpu" "cu128-slim" "cu128-megapak" "latest"; do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "https://hub.docker.com/v2/repositories/yanwk/comfyui-boot/tags/${TAG}")
    if [ "$STATUS" = "200" ]; then
        echo "  ✓ ${TAG} - available"
    else
        echo "  ✗ ${TAG} - not found"
    fi
done

echo ""
echo "For full tag list, visit:"
echo "  https://hub.docker.com/r/yanwk/comfyui-boot/tags"
echo ""
echo "To update image tag:"
echo "  1. Edit values.yaml or values.prod.yaml"
echo "  2. Update image.tag to desired version"
echo "  3. Commit and push changes"
