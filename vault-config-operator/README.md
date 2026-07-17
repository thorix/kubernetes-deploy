# Vault Config Operator

Manages Vault configuration (policies, auth methods, secret engines) as Kubernetes CRDs for GitOps workflows.

## Overview

This operator allows you to declare Vault configuration as Kubernetes custom resources, enabling:
- **Policies** as CRDs (co-located with applications)
- **Auth methods** (Kubernetes, LDAP, JWT/OIDC, etc.)
- **Secret engines** (KV, database, PKI, etc.)
- Automatic reconciliation and cleanup

## Works With

- **Vault Secrets Operator (VSO)**: Handles syncing secrets FROM Vault TO Kubernetes
- **This operator**: Handles configuring Vault itself (policies, auth, engines)

## Example: Creating a Policy

```yaml
apiVersion: redhatcop.redhat.io/v1alpha1
kind: Policy
metadata:
  name: myapp-policy
  namespace: myapp
spec:
  # Vault connection
  connection:
    address: http://vault.vault.svc.cluster.local:8200
  # How this CRD authenticates to Vault
  authentication:
    path: kubernetes
    role: vault-config-operator
  # Policy name in Vault
  name: myapp-policy
  # HCL policy definition
  policy: |
    path "kv/data/myapp/*" {
      capabilities = ["read", "list"]
    }
```

## Example: Kubernetes Auth Role

```yaml
apiVersion: redhatcop.redhat.io/v1alpha1
kind: KubernetesAuthEngineRole
metadata:
  name: myapp-role
  namespace: myapp
spec:
  # Vault connection
  connection:
    address: http://vault.vault.svc.cluster.local:8200
  # How this CRD authenticates to Vault
  authentication:
    path: kubernetes
    role: vault-config-operator
  # Kubernetes auth mount path in Vault
  path: kubernetes
  # Role name in Vault (what apps will use to authenticate)
  name: myapp
  # Policies to attach to this role
  policies:
    - myapp-policy
  # Bind to these service accounts
  targetServiceAccounts:
    - default
  # In these namespaces
  targetNamespaces:
    targetNamespaces:
      - myapp
  # Token settings
  tokenTTL: 86400
```

## Supported CRDs

- **Policy** - Vault policies
- **AuthEngineMount** - Enable auth methods
- **KubernetesAuthEngineConfig/Role** - Kubernetes auth
- **SecretEngineMount** - Enable secret engines
- **DatabaseSecretEngineConfig/Role** - Database credentials
- **PKISecretEngineConfig/Role** - Certificates
- **RandomSecret** - Generate random secrets
- **VaultSecret** - Sync Vault secrets to K8s

## Documentation

- [Vault Config Operator GitHub](https://github.com/redhat-cop/vault-config-operator)
- [End-to-End Example](https://github.com/redhat-cop/vault-config-operator/blob/main/docs/end-to-end-example.md)
- [API Reference](https://github.com/redhat-cop/vault-config-operator/blob/main/docs/api-reference.md)

## Bootstrap Required

The operator needs a Vault role to authenticate. Set up in Vault:

```bash
# Enable Kubernetes auth (if not already)
vault auth enable kubernetes

# Configure Kubernetes auth
vault write auth/kubernetes/config \
  kubernetes_host="https://kubernetes.default.svc"

# Create policy for the operator
vault policy write vault-config-operator - <<EOF
# Policy management (both paths for compatibility)
path "sys/policies/acl/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
path "sys/policy/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

# Kubernetes auth role management
path "auth/kubernetes/role/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

# KV v2 secrets engine
path "kv/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
path "kv/data/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
path "kv/metadata/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
EOF

# Create role for the operator
# Note: Uses wildcard namespace to allow CRDs in any namespace to authenticate
vault write auth/kubernetes/role/vault-config-operator \
  bound_service_account_names=default \
  bound_service_account_namespaces='*' \
  policies=vault-config-operator \
  ttl=1h
```
