## ArgoCD Bootstrap Deployment

The goal is to use ArgoCD to deploy everything in the cluster. This enables the same pattern for version patching and automation. The problem is that ArgoCD first needs to be in the cluster before anything else. For this reason, a bootstrap process is required.

### Architecture Overview

This folder follows the same pattern as other applications (like hello-world):

- **chart/argocd/** - Helm chart wrapper for ArgoCD with custom templates
  - Chart.yaml with ArgoCD helm dependency
  - values.yaml with default chart values
  - templates/ - Custom Helm templates (ApplicationSet for bootstrapping other apps)
  - config/ - Configuration files imported by templates

- **deployment/** - Environment-specific deployment configurations
  - values.yaml - Base values for all environments
  - values.prod.yaml - Production-specific overrides
  - values.dev.yaml - Development-specific overrides
  - deploy.yaml - ArgoCD Application manifest for self-management

### Prerequisites

Before deploying ArgoCD, create the GitHub credentials secret:

```bash
# Create the namespace first
kubectl create namespace argocd

# Create the GitHub credentials secret with your Personal Access Token (PAT)
# This secret format is auto-discovered by ArgoCD for repository authentication
kubectl create secret generic argocd-github-creds \
  --namespace argocd \
  --from-literal=type=git \
  --from-literal=url=https://github.com/YOUR_ORG \
  --from-literal=password='YOUR_GITHUB_PAT_HERE'

# Label the secret so ArgoCD auto-discovers it as repository credentials
kubectl label secret argocd-github-creds \
  --namespace argocd \
  argocd.argoproj.io/secret-type=repository
```

**Important:** This secret must be created before deploying ArgoCD. ArgoCD automatically discovers and uses secrets labeled with `argocd.argoproj.io/secret-type=repository` in its namespace. The secret will provide credentials for all repositories under `https://github.com/YOUR_ORG`.

### Bootstrap Process

Cilium CNI must be installed before ArgoCD (ArgoCD requires pod networking).

1. **Install Cilium** (manual, one-time):
   ```bash
   cd ../cilium && ./deploy.sh
   ```
   This installs the CNI so pod networking is available.

2. **Install ArgoCD** (manual, one-time):
   ```bash
   ./deploy.sh
   ```
   This deploys ArgoCD using Helm directly to the cluster.

3. **Self-Management** (automatic, post-bootstrap):
   After bootstrap, apply the ArgoCD Application manifest:
   ```bash
   kubectl apply -f deployment/deploy.yaml
   ```
   This creates an Application resource that points ArgoCD to manage its own deployment from this repo.

4. **Application Bootstrap** (automatic):
   The ApplicationSet in templates/ automatically discovers and deploys other applications from the repo by reading their deployment/deploy.yaml manifests.

5. **Transition to GitOps** (manual, one-time):
   Once ArgoCD has synced both the cilium and argocd applications:
   ```bash
   cd ../cilium && ./deploy.sh --cleanup
   ./deploy.sh --cleanup
   ```
   This removes Helm release tracking so ArgoCD fully manages both.

### Chart Management

Update the ArgoCD chart dependency:
```bash
cd chart/argocd
helm dependency update
```

Check for latest ArgoCD chart version:
```bash
./current-version.sh
```

### Deployment Commands

Deploy to specific environment:
```bash
# Development
helm upgrade --install --namespace argocd --values values.yaml --values values.dev.yaml argocd ./chart/argocd

# Production
helm upgrade --install --namespace argocd --values values.yaml --values values.prod.yaml argocd ./chart/argocd
```

### Accessing ArgoCD

Get admin password:
```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
```

Port forward (for local access):
```bash
kubectl port-forward svc/argocd-server -n argocd 8080:443
```

Access via ingress (configured domain):
```bash
# Access at configured domain (e.g., https://argocd.lan)
```

### Testing Configuration

Before deploying to a cluster, test your Helm configuration locally:

#### Test Template Rendering

Verify that templates render correctly with your values:
```bash
# Test production values
helm template argocd ./chart/argocd --values values.yaml --values values.prod.yaml

# Test development values
helm template argocd ./chart/argocd --values values.yaml --values values.dev.yaml
```

#### Verify Specific Resources

Check that critical resources are configured correctly:
```bash
# Verify ArgoCD server service type (should be LoadBalancer in prod)
helm template argocd ./chart/argocd --values values.yaml --values values.prod.yaml | grep -A 10 "name: argocd-server" | grep "type:"

# Check ApplicationSet configuration
helm template argocd ./chart/argocd --values values.yaml --show-only templates/applicationset.yaml

# Verify resource limits and replicas
helm template argocd ./chart/argocd --values values.yaml --values values.prod.yaml | grep -E "replicas:|limits:|requests:" | head -20
```

#### Dry-Run Deployment

Test the deployment without actually applying to the cluster:
```bash
# Development dry-run
helm upgrade --install --namespace argocd --values values.yaml --values values.dev.yaml argocd ./chart/argocd --dry-run --debug

# Production dry-run
helm upgrade --install --namespace argocd --values values.yaml --values values.prod.yaml argocd ./chart/argocd --dry-run --debug
```

#### Important Notes for Subchart Configuration

The ArgoCD chart is included as a subchart with alias `argocd`. All ArgoCD-specific configuration **must be nested under the `argocd:` key** in values files:

```yaml
# ✅ Correct - nested under argocd:
argocd:
  server:
    service:
      type: LoadBalancer

# ❌ Wrong - at root level (will be ignored)
server:
  service:
    type: LoadBalancer
```

When making changes to values files, always verify with `helm template` to ensure values are being applied correctly.

### Complete Removal

To fully remove ArgoCD from the cluster:
```bash
helm delete argocd -n argocd
kubectl delete namespace argocd
kubectl delete crd applications.argoproj.io applicationsets.argoproj.io appprojects.argoproj.io
```
