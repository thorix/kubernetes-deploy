# Vault Secrets Operator

Vault Secrets Operator (VSO) is the official HashiCorp operator for syncing secrets from Vault to Kubernetes. It provides native integration with Vault and supports various secret types.

## Overview

This deployment installs Vault Secrets Operator using the official Helm chart. The operator enables applications to:

1. **Fetch secrets from Vault** - Direct integration with HashiCorp Vault
2. **Automatically sync secrets** - Keep Kubernetes secrets in sync with Vault
3. **Refresh secrets periodically** - Update secrets based on configured intervals
4. **Multiple secret types** - Static secrets, dynamic secrets, PKI certificates

## Components

- **Controller Manager** - Main controller that watches VaultStaticSecret, VaultDynamicSecret, and other VSO resources
- **Webhook** - Validates VSO custom resources

## Architecture

```
┌─────────────────────┐
│   HashiCorp Vault   │
│                     │
└──────────┬──────────┘
           │
           │ Authenticate & Fetch
           │
┌──────────▼──────────┐
│  Vault Secrets      │
│     Operator        │
└──────────┬──────────┘
           │
           │ Create/Update
           │
┌──────────▼──────────┐
│  Kubernetes Secret  │
│  (Native K8s obj)   │
└─────────────────────┘
```

## Custom Resource Definitions (CRDs)

- **VaultConnection** - Defines connection to Vault server (namespace-scoped)
- **VaultAuth** - Defines authentication method to Vault (namespace-scoped)
- **VaultStaticSecret** - Syncs static secrets from Vault KV
- **VaultDynamicSecret** - Requests dynamic credentials from Vault
- **VaultPKISecret** - Manages PKI certificates from Vault

## Example Usage

### 1. Create a VaultConnection

```yaml
apiVersion: secrets.hashicorp.com/v1beta1
kind: VaultConnection
metadata:
  name: vault-connection
  namespace: my-app
spec:
  address: http://vault.vault.svc.cluster.local:8200
  skipTLSVerify: true
```

### 2. Create a VaultAuth

```yaml
apiVersion: secrets.hashicorp.com/v1beta1
kind: VaultAuth
metadata:
  name: vault-auth
  namespace: my-app
spec:
  vaultConnectionRef: vault-connection
  method: kubernetes
  mount: kubernetes
  kubernetes:
    role: my-app
    serviceAccount: default
    audiences:
      - vault
```

### 3. Create a VaultStaticSecret

```yaml
apiVersion: secrets.hashicorp.com/v1beta1
kind: VaultStaticSecret
metadata:
  name: my-app-secrets
  namespace: my-app
spec:
  type: kv-v2
  vaultAuthRef: vault-auth
  mount: kv
  path: my-app/credentials
  refreshAfter: 1h
  destination:
    name: my-app-secrets
    create: true
```

This will:
- Connect to Vault using the VaultConnection configuration
- Authenticate using Kubernetes auth via VaultAuth
- Fetch the secret at path `kv/data/my-app/credentials`
- Create a Kubernetes Secret named `my-app-secrets`
- Refresh the secret every hour

## Deployment Environments

### Base Configuration (values.yaml)
- Minimal resource requests
- Single replica controller

### Production Configuration (values.prod.yaml)
- 2 replicas for high availability
- Increased resource limits

## Manual Deployment

```bash
# Update Helm dependencies
helm dependency update

# Deploy to production
helm upgrade --install \
  --create-namespace \
  --namespace vault-secrets-operator-system \
  --values values.yaml \
  --values values.prod.yaml \
  vault-secrets-operator .
```

## Verification

Check that the operator is running:

```bash
kubectl get pods -n vault-secrets-operator-system
kubectl get crds | grep secrets.hashicorp.com
```

You should see:
- `vault-secrets-operator` controller pod running
- CRDs: `vaultauths`, `vaultconnections`, `vaultstaticsecrets`, `vaultdynamicsecrets`, etc.

## Integration with Applications

Applications like `cloudflare-tunnel` use Vault Secrets Operator to fetch credentials from Vault. The operator:

1. Uses VaultConnection to connect to Vault
2. Authenticates via VaultAuth (Kubernetes service account)
3. Fetches secrets using VaultStaticSecret
4. Creates/updates Kubernetes Secrets
5. Keeps them synchronized with Vault

## Advantages over External Secrets Operator

- **Official HashiCorp solution** - Maintained by Vault team
- **Native Vault integration** - Optimized for Vault workflows
- **Simpler configuration** - Fewer moving parts
- **Better Vault support** - Full feature parity with Vault

## References

- [Vault Secrets Operator Documentation](https://developer.hashicorp.com/vault/docs/platform/k8s/vso)
- [Helm Chart Repository](https://github.com/hashicorp/vault-secrets-operator)
- [API Reference](https://developer.hashicorp.com/vault/docs/platform/k8s/vso/api-reference)
