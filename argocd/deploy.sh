#!/usr/bin/env bash
set -eu -o pipefail

RELEASE_NAME=argocd
NAMESPACE=argocd
ENVIRONMENT=prod
CLEANUP_MODE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --cleanup)
            CLEANUP_MODE=true
            shift
            ;;
        dev|prod)
            ENVIRONMENT=$1
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS] [ENVIRONMENT]"
            echo ""
            echo "OPTIONS:"
            echo "  --cleanup    Remove helm deployment and Application to enable GitOps self-management"
            echo "  -h, --help   Show this help message"
            echo ""
            echo "ENVIRONMENT:"
            echo "  dev          Deploy with development configuration"
            echo "  prod         Deploy with production configuration (default)"
            echo ""
            echo "EXAMPLES:"
            echo "  $0              # Deploy to prod"
            echo "  $0 dev          # Deploy to dev"
            echo "  $0 --cleanup    # Transition to GitOps self-management"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Run '$0 --help' for usage information"
            exit 1
            ;;
    esac
done

[ -z "${RELEASE_NAME+x}" ] && echo "Need to set RELEASE_NAME" && exit 1;
[ -z "${NAMESPACE+x}" ] && echo "Need to set NAMESPACE" && exit 1;

# Cleanup mode - Transition to GitOps self-management
if [ "$CLEANUP_MODE" = true ]; then
    CLUSTER_NAME=$(kubectl config view --minify -o jsonpath='{.clusters[].name}')

    echo "=========================================="
    echo "ArgoCD GitOps Transition"
    echo "=========================================="
    echo "Cluster: ${CLUSTER_NAME}"
    echo ""
    echo "This transitions ArgoCD from Helm to GitOps self-management."
    echo "ArgoCD will continue running and can update itself via Git."
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
    echo "[1/4] Verifying ArgoCD Application exists..."
    if ! kubectl get application argocd -n ${NAMESPACE} &>/dev/null; then
        echo "ERROR: ArgoCD Application not found"
        echo "The ApplicationSet should have created it from argocd/deploy.yaml"
        echo ""
        echo "Check: kubectl get applications -n ${NAMESPACE}"
        echo "Check: kubectl describe applicationset bootstrap-apps -n ${NAMESPACE}"
        exit 1
    fi
    echo "✓ ArgoCD Application exists"

    echo ""
    echo "[2/4] Verifying ArgoCD Application is synced..."
    SYNC_STATUS=$(kubectl get application argocd -n ${NAMESPACE} -o jsonpath='{.status.sync.status}' 2>/dev/null)
    HEALTH_STATUS=$(kubectl get application argocd -n ${NAMESPACE} -o jsonpath='{.status.health.status}' 2>/dev/null)

    if [ "$SYNC_STATUS" != "Synced" ] || [ "$HEALTH_STATUS" != "Healthy" ]; then
        echo "WARNING: Application not ready (Sync: ${SYNC_STATUS}, Health: ${HEALTH_STATUS})"
        echo ""
        read -p "Continue anyway? (y/n) " yn
        case $yn in
            [Nn]* )
                echo "Aborting. Wait for Application to sync or check for errors."
                exit 1
                ;;
        esac
    else
        echo "✓ Application is Synced and Healthy"
    fi

    echo ""
    echo "[3/4] Deleting Helm release tracking Secret..."
    # Helm stores release info in Secrets with label owner=helm
    # Deleting these removes Helm's knowledge of the release without affecting resources
    HELM_SECRETS=$(kubectl get secrets -n ${NAMESPACE} -l owner=helm,name=${RELEASE_NAME} -o name 2>/dev/null)

    if [ -n "$HELM_SECRETS" ]; then
        echo "$HELM_SECRETS" | xargs kubectl delete -n ${NAMESPACE} &>/dev/null
        if [ $? -eq 0 ]; then
            echo "✓ Helm release tracking removed"
        else
            echo "ERROR: Failed to delete Helm secrets"
            exit 1
        fi
    else
        echo "⚠ No Helm release secrets found"
    fi

    echo ""
    echo "[4/4] Verifying ArgoCD is still running..."
    RUNNING_PODS=$(kubectl get pods -n ${NAMESPACE} --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l)

    if [ "$RUNNING_PODS" -gt 0 ]; then
        echo "✓ ArgoCD pods running ($RUNNING_PODS pods)"
    else
        echo "ERROR: No ArgoCD pods running!"
        exit 1
    fi

    echo ""
    echo "=========================================="
    echo "✓ Transition Complete"
    echo "=========================================="
    echo "ArgoCD is now self-managed via Git"
    echo ""
    echo "Verify: kubectl get application argocd -n ${NAMESPACE}"
    echo ""
    exit 0
fi

# Validate environment
if [[ ! "$ENVIRONMENT" =~ ^(dev|prod)$ ]]; then
    echo "Invalid environment: ${ENVIRONMENT}"
    echo "Usage: $0 [dev|prod]"
    echo "  Default: prod"
    exit 1
fi

ENV_VALUES_FILE="values.${ENVIRONMENT}.yaml"
if [ ! -f "$ENV_VALUES_FILE" ]; then
    echo "Error: Environment values file not found: ${ENV_VALUES_FILE}"
    exit 1
fi

# Confirm we're executing against the right cluster
CLUSTER_NAME=$(kubectl config view --minify -o jsonpath='{.clusters[].name}')
echo "Deploying ArgoCD"
echo "Cluster: ${CLUSTER_NAME}"
echo "Environment: ${ENVIRONMENT}"
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
echo "[1/4] Updating Helm repositories..."
helm repo add argo https://argoproj.github.io/argo-helm --force-update &>/dev/null
helm dependency update --skip-refresh &>/dev/null
echo "✓ Helm repositories updated"

echo ""
echo "[2/4] Checking CRDs..."
SKIP_CRDS=""
DISABLE_APPSET=""

if kubectl get crd applicationsets.argoproj.io &>/dev/null; then
    # CRD exists - check if managed by Helm
    CRD_MANAGED_BY=$(kubectl get crd applicationsets.argoproj.io -o jsonpath='{.metadata.labels.app\.kubernetes\.io/managed-by}' 2>/dev/null)
    if [ "$CRD_MANAGED_BY" != "Helm" ]; then
        SKIP_CRDS="--skip-crds"
        echo "✓ Using existing CRDs"
    else
        echo "✓ Will update Helm-managed CRDs"
    fi
else
    # No CRDs - disable ApplicationSet, will be created by bootstrap
    DISABLE_APPSET="--set applicationSet.enabled=false"
    echo "✓ Will install CRDs (ApplicationSet via bootstrap)"
fi

echo ""
echo "[3/4] Deploying ArgoCD with Helm..."
helm upgrade \
  --install \
  --create-namespace \
  --reset-values \
  --namespace ${NAMESPACE} \
  --values values.yaml \
  --values ${ENV_VALUES_FILE} \
  ${SKIP_CRDS} \
  ${DISABLE_APPSET} \
  ${RELEASE_NAME} . &>/dev/null

if [ $? -eq 0 ]; then
    echo "✓ Helm deployment complete"
else
    echo "ERROR: Helm deployment failed"
    exit 1
fi

echo ""
echo "[4/4] Applying bootstrap Application..."
kubectl apply -f application.yaml &>/dev/null
kubectl wait --for=condition=available --timeout=180s deployment/argocd-server -n ${NAMESPACE} &>/dev/null

if kubectl get applicationset bootstrap-apps -n ${NAMESPACE} &>/dev/null 2>&1; then
    echo "✓ Bootstrap complete"
else
    echo "⚠ ApplicationSet not ready yet (may take a moment)"
fi

echo ""
echo "=========================================="
echo "✓ ArgoCD Deployed"
echo "=========================================="
echo ""
echo "Access UI:"
echo "  kubectl port-forward svc/argocd-server -n ${NAMESPACE} 8080:443"
echo "  https://localhost:8080 (admin / <get password below>)"
echo ""
echo "Get admin password:"
echo "  kubectl -n ${NAMESPACE} get secret argocd-initial-admin-secret -o jsonpath=\"{.data.password}\" | base64 -d"
echo ""
echo "Monitor applications:"
echo "  kubectl get applications -n ${NAMESPACE} -w"
echo ""
echo "Transition to GitOps self-management:"
echo "  ./deploy.sh --cleanup"
echo ""
