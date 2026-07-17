#!/usr/bin/env bash
set -eu -o pipefail

RELEASE_NAME=cilium
NAMESPACE=kube-system
CHART_VERSION="1.18.3"
CLEANUP_MODE=false

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VALUES_FILE="${SCRIPT_DIR}/values.yaml"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --cleanup)
            CLEANUP_MODE=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Bootstrap Cilium CNI before ArgoCD is available."
            echo "After ArgoCD is running, use --cleanup to transition to GitOps management."
            echo ""
            echo "OPTIONS:"
            echo "  --cleanup    Remove Helm release tracking to enable ArgoCD management"
            echo "  -h, --help   Show this help message"
            echo ""
            echo "EXAMPLES:"
            echo "  $0              # Bootstrap Cilium install"
            echo "  $0 --cleanup    # Transition to ArgoCD management"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Run '$0 --help' for usage information"
            exit 1
            ;;
    esac
done

# Cleanup mode - Transition to ArgoCD management
if [ "$CLEANUP_MODE" = true ]; then
    CLUSTER_NAME=$(kubectl config view --minify -o jsonpath='{.clusters[].name}')

    echo "=========================================="
    echo "Cilium → ArgoCD Transition"
    echo "=========================================="
    echo "Cluster: ${CLUSTER_NAME}"
    echo ""
    echo "This removes Helm release tracking so ArgoCD can adopt Cilium."
    echo "Cilium will continue running uninterrupted."
    echo ""

    while true; do
        read -p "Continue? (y/n) " yn
        case $yn in
            [Yy]* ) break;;
            [Nn]* ) exit 1;;
            * ) echo "Please answer yes or no.";;
        esac
    done

    echo ""
    echo "[1/3] Verifying ArgoCD has synced Cilium application..."
    if ! kubectl get application cilium -n argocd &>/dev/null; then
        echo "ERROR: ArgoCD Cilium application not found"
        echo "Make sure ArgoCD is running and has synced cilium/deploy.yaml"
        echo ""
        echo "Check: kubectl get applications -n argocd"
        exit 1
    fi

    SYNC_STATUS=$(kubectl get application cilium -n argocd -o jsonpath='{.status.sync.status}' 2>/dev/null)
    HEALTH_STATUS=$(kubectl get application cilium -n argocd -o jsonpath='{.status.health.status}' 2>/dev/null)

    if [ "$SYNC_STATUS" != "Synced" ] || [ "$HEALTH_STATUS" != "Healthy" ]; then
        echo "WARNING: Cilium application not ready (Sync: ${SYNC_STATUS}, Health: ${HEALTH_STATUS})"
        read -p "Continue anyway? (y/n) " yn
        case $yn in
            [Nn]* ) exit 1;;
        esac
    else
        echo "✓ Cilium application is Synced and Healthy"
    fi

    echo ""
    echo "[2/3] Deleting Helm release tracking secrets..."
    HELM_SECRETS=$(kubectl get secrets -n ${NAMESPACE} -l owner=helm,name=${RELEASE_NAME} -o name 2>/dev/null)

    if [ -n "$HELM_SECRETS" ]; then
        echo "$HELM_SECRETS" | xargs kubectl delete -n ${NAMESPACE} &>/dev/null
        echo "✓ Helm release tracking removed"
    else
        echo "⚠ No Helm release secrets found (already cleaned up?)"
    fi

    echo ""
    echo "[3/3] Verifying Cilium is still running..."
    RUNNING_PODS=$(kubectl get pods -n ${NAMESPACE} -l k8s-app=cilium --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l)

    if [ "$RUNNING_PODS" -gt 0 ]; then
        echo "✓ Cilium agent pods running ($RUNNING_PODS pods)"
    else
        echo "ERROR: No Cilium agent pods running!"
        exit 1
    fi

    echo ""
    echo "=========================================="
    echo "✓ Transition Complete"
    echo "=========================================="
    echo "Cilium is now managed by ArgoCD"
    echo ""
    echo "Verify: kubectl get application cilium -n argocd"
    echo ""
    exit 0
fi

# Bootstrap install
CLUSTER_NAME=$(kubectl config view --minify -o jsonpath='{.clusters[].name}')

echo "=========================================="
echo "Cilium CNI Bootstrap"
echo "=========================================="
echo "Cluster:       ${CLUSTER_NAME}"
echo "Chart version: ${CHART_VERSION}"
echo ""

if [ ! -f "$VALUES_FILE" ]; then
    echo "Error: Values file not found: ${VALUES_FILE}"
    exit 1
fi

while true; do
    read -p "Continue? (y/n) " yn
    case $yn in
        [Yy]* ) break;;
        [Nn]* ) exit 1;;
        * ) echo "Please answer yes or no.";;
    esac
done

echo ""
echo "[1/3] Adding Cilium Helm repository..."
helm repo add cilium https://helm.cilium.io/ --force-update &>/dev/null
helm repo update cilium &>/dev/null
echo "✓ Helm repository ready"

echo ""
echo "[2/3] Installing Cilium..."
helm upgrade \
  --install \
  --namespace ${NAMESPACE} \
  --values "${VALUES_FILE}" \
  --version ${CHART_VERSION} \
  ${RELEASE_NAME} cilium/cilium &>/dev/null

if [ $? -eq 0 ]; then
    echo "✓ Helm install complete"
else
    echo "ERROR: Helm install failed"
    exit 1
fi

echo ""
echo "[3/3] Waiting for Cilium to be ready..."
kubectl rollout status daemonset/cilium -n ${NAMESPACE} --timeout=300s &>/dev/null

if [ $? -eq 0 ]; then
    echo "✓ Cilium agents ready"
else
    echo "WARNING: Cilium rollout not complete within timeout"
    echo "Check: kubectl get pods -n ${NAMESPACE} -l k8s-app=cilium"
fi

# Verify connectivity
echo ""
CILIUM_POD=$(kubectl get pods -n ${NAMESPACE} -l k8s-app=cilium -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ -n "$CILIUM_POD" ]; then
    MTU=$(kubectl exec -n ${NAMESPACE} ${CILIUM_POD} -- cilium-dbg status --verbose 2>/dev/null | grep "MTU updated" | grep -oP '\(\K[0-9]+' || echo "unknown")
    echo "Pod MTU: ${MTU}"
fi

echo ""
echo "=========================================="
echo "✓ Cilium Deployed"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Deploy ArgoCD:  cd ../argocd && ./deploy.sh"
echo "  2. Wait for ArgoCD to sync Cilium application"
echo "  3. Transition:     ./deploy.sh --cleanup"
echo ""
