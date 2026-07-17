# Cloudflare Zero Trust Tunnel

Kubernetes deployment for Cloudflare Zero Trust tunnels, providing secure ingress to cluster services without exposing them directly to the internet.

## Overview

This deployment:
- Runs `cloudflared` to create a secure tunnel to Cloudflare
- Retrieves tunnel credentials from HashiCorp Vault via Vault Secrets Operator
- Provides high availability with multiple replicas
- Requires no inbound firewall rules or public IPs

## Prerequisites

### Required
1. **Cloudflare Account**: Active Cloudflare account with domain configured
2. **Cloudflare Tunnel**: Create a tunnel using `cloudflared tunnel create <name>`
3. **Tunnel Token**: Generated token from Cloudflare
4. **HashiCorp Vault**: Vault instance running in the cluster
5. **Vault Secrets Operator**: Installed and configured for Vault integration
6. **Vault Config Operator**: Installed for automatic policy/role management (see `vault-config-operator/README.md`)

### Optional
- Multiple replicas for high availability

## Initial Setup

### 1. Install cloudflared CLI (on your local machine)

**For Ubuntu/Linux:**
```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Install prerequisite packages
sudo apt install curl lsb-release -y

# Add Cloudflare GPG key
curl -L https://pkg.cloudflare.com/cloudflare-main.gpg | \
  sudo tee /usr/share/keyrings/cloudflare-archive-keyring.gpg >/dev/null

# Add Cloudflared repository
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/cloudflare-archive-keyring.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main" | \
  sudo tee /etc/apt/sources.list.d/cloudflared.list

# Update package list and install
sudo apt update
sudo apt install cloudflared
```

### 2. Create Cloudflare Tunnel

```bash
# Login to Cloudflare
cloudflared tunnel login

# Create a new tunnel
cloudflared tunnel create my-k8s-tunnel

# Get the tunnel token (save this for later)
cloudflared tunnel token <TUNNEL_NAME_OR_UUID>
```

### 3. Store Tunnel Token in Vault

```bash
# Store the tunnel token in Vault
# Replace <TUNNEL_TOKEN> with the actual token from step 2
vault kv put kv/cloudflare/tunnel-credentials token="<TUNNEL_TOKEN>"

# Verify the token was stored correctly
vault kv get kv/cloudflare/tunnel-credentials

# IMPORTANT: Verify the token field contains the correct tunnel ID
# Decode the token to check the tunnel UUID:
vault kv get -field=token kv/cloudflare/tunnel-credentials | cut -d. -f1 | base64 -d | jq .t
# This should match the tunnel UUID from 'cloudflared tunnel list'
```

**Important Notes:**
- The secret key MUST be named `token` (not `credentials.json` or other names)
- Verify the token contains the correct tunnel ID before deploying
- If you see "Unauthorized: Failed to get tunnel" errors, the token likely references a deleted/wrong tunnel

### 4. Vault Policy and Auth Role (Automatic)

The Vault policy and Kubernetes auth role are **automatically created** by the vault-config-operator when this chart is deployed. The chart includes:

- `vault-policy.yaml` - Creates the `cloudflare-tunnel` policy in Vault with read access to tunnel credentials
- `vault-auth-role.yaml` - Creates the `cloudflare-tunnel` Kubernetes auth role bound to the service account

**Prerequisites**: The vault-config-operator must be installed and configured. See `vault-config-operator/README.md` for setup instructions.

**Verification** (after deployment):

```bash
# Check the Policy CR status
kubectl describe policies.redhatcop.redhat.io cloudflare-tunnel -n cloudflare-tunnel

# Check the KubernetesAuthEngineRole CR status
kubectl describe kubernetesauthengineroles.redhatcop.redhat.io cloudflare-tunnel -n cloudflare-tunnel

# Verify in Vault
vault policy read cloudflare-tunnel
vault read auth/kubernetes/role/cloudflare-tunnel
```

### 5. Configure Tunnel Routes

After the tunnel is running, configure routes in Cloudflare Dashboard:
1. Go to Zero Trust > Networks > Tunnels
2. Select your tunnel
3. Add Public Hostname routes:
   - Hostname: `example.yourdomain.com`
   - Service: `http://service-name.namespace.svc.cluster.local:port`

## Installation

This deployment is automatically discovered by ArgoCD via the ApplicationSet.

### Manual Installation (for testing)

```bash
# Install with default values
helm install cloudflare-tunnel . -n cloudflare-tunnel --create-namespace

# Install with production values
helm install cloudflare-tunnel . -n cloudflare-tunnel --create-namespace -f values.prod.yaml
```

## Configuration

### Key Values

| Parameter | Description | Default |
|-----------|-------------|---------|
| `replicaCount` | Number of tunnel replicas | `2` |
| `image.repository` | Cloudflared image repository | `cloudflare/cloudflared` |
| `image.tag` | Image tag | `2025.8.1` |
| `cloudflared.managementDiagnostics` | Enable management diagnostics | `false` |
| `vault.enabled` | Enable Vault integration | `true` |
| `vault.url` | Vault server URL | `http://vault.vault.svc.cluster.local:8200` |
| `vault.secretPath` | Path to tunnel token in Vault | `cloudflare/tunnel-credentials` |
| `vault.auth.role` | Vault Kubernetes auth role | `cloudflare-tunnel` |

### Environment-Specific Values

- **values.yaml**: Base configuration (2 replicas, Vault integration)
- **values.prod.yaml**: Production settings (higher resources)
- **values.dev.yaml**: Development settings (single replica, lower resources)

## Verifying Deployment

### 1. Check Pods are Running

```bash
kubectl get pods -n cloudflare-tunnel
```

Expected output:
```
NAME                                READY   STATUS    RESTARTS   AGE
cloudflare-tunnel-xxxxxxxxx-xxxxx   1/1     Running   0          1m
cloudflare-tunnel-xxxxxxxxx-xxxxx   1/1     Running   0          1m
```

### 2. Check Logs

```bash
kubectl logs -n cloudflare-tunnel -l app.kubernetes.io/name=cloudflare-tunnel
```

Look for messages like:
```
Connection registered connIndex=0
Connection registered connIndex=1
Registered tunnel connection
```

### 3. Verify Secret is Created

```bash
kubectl get secret -n cloudflare-tunnel cloudflare-tunnel-token
```

### 4. Check ExternalSecret Status

```bash
kubectl get vaultstaticsecret -n cloudflare-tunnel
```

The status should show `SecretSynced: True`.

## Troubleshooting

### Pod CrashLoopBackOff

**Check logs:**
```bash
kubectl logs -n cloudflare-tunnel -l app.kubernetes.io/name=cloudflare-tunnel
```

Common issues:
- **Invalid token**: Verify the token stored in Vault is correct
- **Vault connection failed**: Check Vault is running and accessible
- **Auth failed**: Verify the Vault role is configured correctly

### Secret Not Created

**Check ExternalSecret status:**
```bash
kubectl describe vaultstaticsecret -n cloudflare-tunnel
```

Common issues:
- **Vault role not found**: Create the Vault Kubernetes auth role
- **Policy not assigned**: Ensure the role has the cloudflare-tunnel-ro policy
- **Secret path incorrect**: Verify the path in Vault matches values.yaml

### Tunnel Not Connecting

**Verify tunnel token:**
```bash
# Get token from Vault
vault kv get kv/cloudflare/tunnel-credentials

# Verify it matches your tunnel
cloudflared tunnel list
```

**Check Cloudflare Dashboard:**
- Go to Zero Trust > Networks > Tunnels
- Verify your tunnel shows as "Healthy"
- Check the "Connectors" tab shows active connections

### Vault Secrets Operator Issues

**Verify VSO is installed:**
```bash
kubectl get pods -n vault-secrets-operator-system
```

**Check VaultAuth:**
```bash
kubectl get vaultauth -n cloudflare-tunnel
kubectl describe vaultauth -n cloudflare-tunnel
```

**Check VaultStaticSecret:**
```bash
kubectl get vaultstaticsecret -n cloudflare-tunnel
kubectl describe vaultstaticsecret -n cloudflare-tunnel
```

## How It Works

1. **VaultConnection** defines the connection to HashiCorp Vault
2. **VaultAuth** configures Kubernetes authentication with Vault
3. **VaultStaticSecret** fetches the tunnel token from Vault path `kv/cloudflare/tunnel-credentials`
4. **Kubernetes Secret** is created with the token
5. **Deployment** mounts the secret and uses it to authenticate the tunnel
6. **Cloudflared** establishes persistent connections to Cloudflare's edge

## Security Considerations

- **Token Security**: Tunnel token is stored in Vault, never in git
- **RBAC**: ServiceAccount has minimal permissions
- **No Inbound Ports**: Tunnel makes outbound HTTPS connections only
- **Credential Rotation**: VaultStaticSecret refreshes credentials every hour

## Additional Resources

**Cloudflare:**
- [Cloudflare Tunnel Documentation](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/)
- [Cloudflared GitHub](https://github.com/cloudflare/cloudflared)

**Vault Integration:**
- [Vault Secrets Operator](https://developer.hashicorp.com/vault/docs/platform/k8s/vso)
- [VaultStaticSecret Documentation](https://developer.hashicorp.com/vault/docs/platform/k8s/vso/api-reference)

## Version Management

### Checking for Updates

Use the `current-version.sh` script to check for the latest cloudflared version:

```bash
./current-version.sh
```

**What it does:**
- Checks current cloudflared version from Chart.yaml and values.yaml
- Fetches latest version from GitHub releases
- Provides update commands if newer version available

**Important:** Cloudflare recommends always running the latest version for security and compatibility with their edge network.

## Standard Deployment Pattern

This deployment follows the standard pattern used across all deployments in this repository:

### 1. Vault Integration Pattern
```yaml
VaultConnection → VaultAuth → VaultStaticSecret → Kubernetes Secret → Pod
```

**Components:**
- `VaultConnection`: Defines Vault server URL and connection settings
- `VaultAuth`: Configures Kubernetes authentication method
- `VaultStaticSecret`: Specifies which secret to fetch and how often to refresh
- Kubernetes Secret: Auto-created and managed by VSO
- Pod: Mounts the secret as environment variables or files

### 2. Required Vault Configuration

Every deployment using Vault requires:

1. **Vault Policy** - Defines what paths the role can access (auto-created by vault-config-operator)
2. **Kubernetes Auth Role** - Binds service account to policy (auto-created by vault-config-operator)
3. **Secret in Vault** - The actual credential data (manual setup required)

**With vault-config-operator**, policies and roles are defined as Kubernetes CRDs:
- `Policy` - Creates the Vault policy
- `KubernetesAuthEngineRole` - Creates the Kubernetes auth role

See `vault-config-operator/README.md` for setup instructions.

### 3. Troubleshooting Vault Integration

**Check VSO logs:**
```bash
kubectl logs -n vault-secrets-operator-system deployment/vault-secrets-operator-controller-manager --tail=50 | grep <namespace>
```

**Common errors:**
- `403 permission denied` - Vault Kubernetes auth not configured or wrong audience
- `Unauthorized` - Vault role doesn't exist or namespace mismatch
- `SecretStore not ready` - VaultAuth/VaultConnection has errors

**Debug steps:**
1. Verify Vault role exists: `vault read auth/kubernetes/role/<DEPLOYMENT_NAME>`
2. Verify policy exists: `vault policy read <POLICY_NAME>`
3. Verify secret exists: `vault kv get <SECRET_PATH>`
4. Check VaultStaticSecret status: `kubectl describe vaultstaticsecret -n <namespace>`

## Notes

- **High Availability**: Multiple replicas ensure tunnel stays up during pod restarts
- **Auto-updates Disabled**: `--no-autoupdate` prevents automatic cloudflared updates
- **Management Diagnostics**: Disabled by default to reduce overhead
- **Namespace**: Deployed to `cloudflare-tunnel` namespace by default
- **Token Refresh**: VaultStaticSecret refreshes the token from Vault every hour
- **Protocol**: Uses HTTP/2 over TCP port 443 (not QUIC/UDP) for better firewall compatibility
