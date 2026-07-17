# cert-manager

Automatic TLS certificate management with cert-manager v1.19.2.

## Features

- **Self-signed CA**: For internal services (1 year validity)
- **Let's Encrypt**: Production wildcard certificates via DNS-01 challenge
- **Vault Integration**: Cloudflare API token stored securely in Vault

## ClusterIssuers

| Name | Type | Use Case |
|------|------|----------|
| `selfsigned-issuer` | Self-signed | Bootstrap CA certificate |
| `selfsigned-ca-issuer` | CA | Internal services (*.rye) |
| `letsencrypt-prod` | ACME | Public services (wildcard domain, configured in overlay) |

## Vault Setup

The Cloudflare API token is stored in Vault. The policy and auth role are created automatically via vault-config-operator CRDs.

### Add the Secret to Vault

```bash
# Path: kv/cert-manager/cloudflare
# Key: api-token
vault kv put kv/cert-manager/cloudflare \
  api-token="your-cloudflare-api-token"
```

That's it! The chart automatically creates:
- `Policy` - Vault policy allowing read access to `kv/data/cert-manager/cloudflare`
- `KubernetesAuthEngineRole` - Binds the `cert-manager` service account to the policy
- `VaultConnection` - Connection details for vault-secrets-operator
- `VaultAuth` - Authentication configuration
- `VaultStaticSecret` - Syncs the token to a Kubernetes secret

## Cloudflare API Token

Create a Cloudflare API token with the following permissions:

- **Zone - DNS - Edit** (for your DNS zone)
- **Zone - Zone - Read** (for your DNS zone)

### Creating the Token

1. Go to [Cloudflare API Tokens](https://dash.cloudflare.com/profile/api-tokens)
2. Click "Create Token"
3. Use "Edit zone DNS" template
4. Configure:
   - Zone Resources: Include → Specific zone → (your zone)
   - Permissions: Zone - DNS - Edit
5. Create and copy the token

## Certificates Created

| Certificate | Secret Name | DNS Names | Issuer |
|-------------|-------------|-----------|--------|
| wildcard (env-specific) | wildcard-tls | *.domain, domain | letsencrypt-prod |

The wildcard certificate is created in `kube-system` namespace and can be referenced by any HTTPRoute.

## Deployment Order

1. Deploy `cert-manager` (creates CRDs, ClusterIssuers, Vault resources)
2. Add Cloudflare API token to Vault at `kv/cert-manager/cloudflare`
3. Wait for Vault to sync the secret (check with `kubectl get secret cloudflare-api-token -n cert-manager`)
4. Deploy `cluster-infrastructure` (creates HTTPS Gateway referencing the certificates)

## Troubleshooting

### Check Certificate Status

```bash
kubectl get certificates -A
kubectl describe certificate wildcard-example-io -n kube-system
```

### Check ClusterIssuer Status

```bash
kubectl get clusterissuers
kubectl describe clusterissuer letsencrypt-prod
```

### Check Vault Resources

```bash
# Policy and auth role (vault-config-operator)
kubectl get policies -n cert-manager
kubectl get kubernetesauthengineroles -n cert-manager

# Secret sync (vault-secrets-operator)
kubectl get vaultstaticsecrets -n cert-manager
kubectl get secret cloudflare-api-token -n cert-manager
```

### Check ACME Challenge

```bash
kubectl get challenges -A
kubectl describe challenge <challenge-name> -n cert-manager
```
