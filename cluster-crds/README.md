# Cluster CRDs

Centralized CustomResourceDefinition management for operators that don't include CRDs in their Helm charts.

## Purpose

This deployment manages CRDs for operators using a GitOps approach:

- **Version Controlled**: CRDs are stored in Git alongside the operators that use them
- **Declarative**: CRD lifecycle managed by ArgoCD
- **Ordered Deployment**: Sync wave ensures CRDs install before operators
- **Explicit**: Clear visibility into what CRDs are deployed

## When to Use This Deployment

**Use cluster-crds for:**
- Operators that require manual CRD installation (like vault-operator)
- Custom CRDs you've created
- CRDs from upstream projects without Helm charts

**Don't use cluster-crds for:**
- Official Helm charts that include CRDs (VSO, Longhorn, cert-manager, etc.)
  - Let those charts manage their own CRDs automatically
  - They handle versioning and upgrades correctly

## Currently Managed CRDs

### Vault Operator (bank-vaults)
- `vaults.vault.banzaicloud.com` - Vault instance configuration
- `vaultpolicies.vault.banzaicloud.com` - Vault policy definitions
- `vaultauthroles.vault.banzaicloud.com` - Vault authentication roles

**Version**: v1.22.3 (should match vault-operator/Chart.yaml appVersion)

## Architecture

```
ArgoCD ApplicationSet Discovery
         │
         ├─> cluster-crds (sync wave: -10)
         │   └─> Installs CRDs first
         │
         ├─> vault-operator (sync wave: 0)
         │   └─> Deploys operator (CRDs already exist)
         │
         └─> Other deployments use VaultPolicy/VaultAuthRole
```

## Deployment

### Via ArgoCD (Recommended)

ArgoCD automatically discovers this via ApplicationSet:

1. Commit changes to `cluster-crds/`
2. Push to Git
3. ArgoCD syncs CRDs (sync wave: -10)
4. Operators deploy after CRDs are ready

### Manual Deployment

For testing or initial bootstrap:

```bash
# Deploy CRDs
helm upgrade --install \
  --create-namespace \
  --namespace default \
  --values values.yaml \
  --values values.prod.yaml \
  cluster-crds .

# Verify CRDs are installed
kubectl get crds | grep vault.banzaicloud.com
```

## Adding New CRDs

### Option 1: Add to This Deployment (Recommended)

1. **Add configuration to values.yaml:**
```yaml
myOperator:
  enabled: true
  version: v1.0.0
  crds:
    - resources.example.com
    - configs.example.com
```

2. **Create template file:**
```bash
# Download CRDs from upstream
kubectl apply --dry-run=client -f \
  https://raw.githubusercontent.com/org/repo/main/config/crd/bases/resources.example.com_resources.yaml \
  -o yaml > templates/my-operator-crds.yaml

# Add conditional and labels:
# {{- if .Values.myOperator.enabled }}
# metadata:
#   annotations:
#     argocd.argoproj.io/sync-wave: "-5"
#   labels:
#     app.kubernetes.io/version: {{ .Values.myOperator.version | quote }}
```

3. **Update values.prod.yaml:**
```yaml
myOperator:
  enabled: true
  version: v1.0.0
```

4. **Commit and push**

### Option 2: Operator-Specific CRD Chart

For operators with many CRDs or complex versioning:

```bash
# Create separate deployment
mkdir my-operator-crds
# Structure like this deployment
# Reference from my-operator README
```

## Updating CRD Versions

When updating an operator (e.g., vault-operator):

1. **Update operator version:**
```bash
# Edit vault-operator/Chart.yaml
appVersion: "v1.23.0"
```

2. **Update CRD version:**
```bash
# Edit cluster-crds/values.prod.yaml
vaultOperator:
  version: v1.23.0
```

3. **Fetch new CRD definitions:**
```bash
# Download from upstream
curl -o templates/vault-operator-crds-new.yaml \
  https://raw.githubusercontent.com/bank-vaults/vault-operator/v1.23.0/config/crd/bases/...

# Compare and update templates/vault-operator-crds.yaml
```

4. **Commit both changes together:**
```bash
git add cluster-crds/ vault-operator/
git commit -m "Update vault-operator to v1.23.0"
git push
```

ArgoCD will:
1. Sync cluster-crds first (wave -10) - Updates CRDs
2. Sync vault-operator (wave 0) - Updates operator with new CRDs available

## Sync Waves Explained

This deployment uses ArgoCD sync wave `-10` to ensure CRDs install before operators:

- **Wave -10**: cluster-crds (this deployment)
- **Wave -5**: CRD resources within templates
- **Wave 0**: Regular deployments (vault-operator, plex, etc.)

This ordering prevents errors like:
```
error: unable to recognize "deployment.yaml": no matches for kind "VaultPolicy"
```

## Verification

Check CRDs are installed:

```bash
# List all vault-operator CRDs
kubectl get crds | grep vault.banzaicloud.com

# Check CRD details
kubectl get crd vaultpolicies.vault.banzaicloud.com -o yaml

# Verify labels
kubectl get crd vaultpolicies.vault.banzaicloud.com \
  -o jsonpath='{.metadata.labels.app\.kubernetes\.io/version}'
```

Test creating a resource:

```bash
# Should not error with "no matches for kind"
kubectl explain vaultpolicy
kubectl explain vaultauthrole
```

## Troubleshooting

### CRDs not installing

**Check ArgoCD Application:**
```bash
kubectl get application cluster-crds -n argocd
kubectl describe application cluster-crds -n argocd
```

**Check sync wave:**
```bash
# CRDs should have sync-wave: -5 annotation
kubectl get crd vaultpolicies.vault.banzaicloud.com \
  -o jsonpath='{.metadata.annotations.argocd\.argoproj\.io/sync-wave}'
```

### Operator deploying before CRDs

**Ensure sync waves are set:**
- cluster-crds deploy.yaml should have `syncWave: "-10"`
- Operator should have default wave (0) or higher

**Check ArgoCD sync order:**
```bash
# Watch applications sync in order
kubectl get applications -n argocd --sort-by=.metadata.annotations.argocd\.argoproj\.io/sync-wave
```

### CRD version mismatch

**Check versions match:**
```bash
# CRD version
kubectl get crd vaultpolicies.vault.banzaicloud.com \
  -o jsonpath='{.metadata.labels.app\.kubernetes\.io/version}'

# Operator version
kubectl get deployment -n vault-operator vault-operator \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
```

They should match!

### Helm chart includes CRDs (shouldn't be here)

If you added a chart with built-in CRDs here by mistake:

1. **Remove from cluster-crds:**
```bash
# Edit values.yaml
myOperator:
  enabled: false
```

2. **Let the operator's Helm chart manage CRDs instead:**
```bash
# Just deploy the operator - it will install its own CRDs
helm install my-operator ...
```

## Best Practices

1. **Keep CRD versions in sync with operators**
   - Update cluster-crds/values.prod.yaml when updating operator Chart.yaml

2. **Use sync waves**
   - CRDs at wave -10
   - Operators at wave 0 or higher

3. **Label CRDs properly**
   - Include app.kubernetes.io/version label
   - Makes version tracking easier

4. **Test updates in dev first**
   - CRD changes can break existing resources
   - Always test CRD updates before production

5. **Version control CRD sources**
   - Document where CRDs came from (upstream repo/version)
   - Makes updates easier

6. **Don't duplicate CRDs**
   - If a Helm chart includes CRDs, don't also add them here
   - Having two sources causes conflicts

## References

- [ArgoCD Sync Waves](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-waves/)
- [Kubernetes CRD Versioning](https://kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/custom-resource-definition-versioning/)
- [Helm CRD Limitations](https://helm.sh/docs/chart_best_practices/custom_resource_definitions/)
