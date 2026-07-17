#!/bin/bash
# Validate Helm charts before deployment
# Usage: ./scripts/validate.sh [app-name] [--prod]
#
# Examples:
#   ./scripts/validate.sh              # Validate all apps
#   ./scripts/validate.sh plex         # Validate plex only
#   ./scripts/validate.sh plex --prod  # Validate plex with prod values
#   ./scripts/validate.sh --prod       # Validate all apps with prod values

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
APP=""
USE_PROD=false

for arg in "$@"; do
    case $arg in
        --prod)
            USE_PROD=true
            ;;
        *)
            APP="$arg"
            ;;
    esac
done

# Find all apps with deploy.yaml
find_apps() {
    find "$REPO_ROOT" -maxdepth 2 -name "deploy.yaml" -type f | while read -r f; do
        dirname "$f" | xargs basename
    done | sort
}

# Get chart path from deploy.yaml
get_chart_path() {
    local app_dir="$1"
    local deploy_yaml="$app_dir/deploy.yaml"

    # Extract path from helm section
    local chart_path=$(grep -A 2 "^helm:" "$deploy_yaml" | grep "path:" | head -1 | sed 's/.*path: *//' | tr -d '"' | tr -d "'")

    if [[ -z "$chart_path" ]]; then
        # Check for chart: (external chart)
        if grep -q "chart:" "$deploy_yaml"; then
            echo "EXTERNAL"
            return
        fi
        # Default to app directory itself
        echo "$app_dir"
    else
        echo "$REPO_ROOT/$chart_path"
    fi
}

# Validate a single app
validate_app() {
    local app_name="$1"
    local app_dir="$REPO_ROOT/$app_name"

    if [[ ! -d "$app_dir" ]]; then
        echo -e "${RED}ERROR: App directory not found: $app_dir${NC}"
        return 1
    fi

    if [[ ! -f "$app_dir/deploy.yaml" ]]; then
        echo -e "${YELLOW}SKIP: No deploy.yaml in $app_name${NC}"
        return 0
    fi

    echo -e "${YELLOW}━━━ Validating: $app_name ━━━${NC}"

    local chart_path=$(get_chart_path "$app_dir")

    if [[ "$chart_path" == "EXTERNAL" ]]; then
        echo -e "${YELLOW}  SKIP: External chart (requires network)${NC}"
        return 0
    fi

    if [[ ! -d "$chart_path" ]]; then
        echo -e "${RED}  ERROR: Chart path not found: $chart_path${NC}"
        return 1
    fi

    # Build values file arguments
    local values_args=""
    if [[ -f "$app_dir/values.yaml" ]]; then
        values_args="-f $app_dir/values.yaml"
    fi
    if [[ "$USE_PROD" == "true" && -f "$app_dir/values.prod.yaml" ]]; then
        values_args="$values_args -f $app_dir/values.prod.yaml"
    fi

    local errors=0

    # Step 1: Helm lint (only if chart has Chart.yaml)
    if [[ -f "$chart_path/Chart.yaml" ]]; then
        echo -n "  Helm lint... "
        if helm lint "$chart_path" $values_args >/dev/null 2>&1; then
            echo -e "${GREEN}OK${NC}"
        else
            echo -e "${RED}FAILED${NC}"
            helm lint "$chart_path" $values_args 2>&1 | head -20
            errors=$((errors + 1))
        fi
    fi

    # Step 2: Helm template
    echo -n "  Helm template... "
    local template_output
    if template_output=$(helm template "$app_name" "$chart_path" $values_args -n "$app_name" 2>&1); then
        echo -e "${GREEN}OK${NC}"
    else
        echo -e "${RED}FAILED${NC}"
        echo "$template_output" | head -20
        errors=$((errors + 1))
        return $errors
    fi

    # Step 3: kubectl dry-run (client-side validation)
    # Note: Some resources may show "Forbidden" errors due to read-only access - these are ignored
    echo -n "  kubectl dry-run... "
    local dryrun_output
    local dryrun_exit_code
    dryrun_output=$(echo "$template_output" | kubectl apply --dry-run=client -f - 2>&1)
    dryrun_exit_code=$?

    # Filter out Forbidden errors (access issues, not template issues)
    local real_errors=$(echo "$dryrun_output" | grep -i "error" | grep -v "Forbidden" | grep -v "cannot get resource" || true)

    if [[ -z "$real_errors" ]]; then
        echo -e "${GREEN}OK${NC}"
        # Show resource count
        local resource_count=$(echo "$dryrun_output" | grep -c "configured\|created\|unchanged" || echo "0")
        echo -e "  ${GREEN}✓ $resource_count resources validated${NC}"
        # Warn about access issues
        if echo "$dryrun_output" | grep -q "Forbidden"; then
            echo -e "  ${YELLOW}⚠ Some resources couldn't be validated (read-only access)${NC}"
        fi
    else
        echo -e "${RED}FAILED${NC}"
        echo "$real_errors" | head -10
        errors=$((errors + 1))
    fi

    return $errors
}

# Main
echo "========================================"
echo "  Helm Chart Validation"
echo "========================================"
echo "Repo: $REPO_ROOT"
echo "Prod values: $USE_PROD"
echo ""

total_errors=0

if [[ -n "$APP" ]]; then
    # Validate single app
    validate_app "$APP" || total_errors=$((total_errors + 1))
else
    # Validate all apps
    for app in $(find_apps); do
        validate_app "$app" || total_errors=$((total_errors + 1))
        echo ""
    done
fi

echo "========================================"
if [[ $total_errors -eq 0 ]]; then
    echo -e "${GREEN}All validations passed!${NC}"
    exit 0
else
    echo -e "${RED}$total_errors app(s) failed validation${NC}"
    exit 1
fi
