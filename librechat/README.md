# LibreChat Deployment

Open source AI chat platform with Anthropic Claude and local llama.cpp support.

## Prerequisites

- Kubernetes cluster with ArgoCD
- Vault with secrets operator (VSO) and vault-config-operator (VCO)
- Tailscale operator for ingress
- Longhorn storage class for MongoDB
- llama.cpp server running in the `lama` namespace

## Vault Secrets Setup

Create the required secrets in Vault before deploying:

```bash
# Anthropic API key
vault kv put kv/librechat/anthropic ANTHROPIC_API_KEY=sk-ant-...

# MongoDB credentials
vault kv put kv/librechat/mongodb username=librechat password=<generate-strong-password>

# JWT secrets for sessions (use: openssl rand -hex 32)
vault kv put kv/librechat/jwt JWT_SECRET=<random-hex> JWT_REFRESH_SECRET=<random-hex>

# Credential encryption keys (use: openssl rand -hex 16 for each)
vault kv put kv/librechat/creds CREDS_KEY=<random-hex-32-chars> CREDS_IV=<random-hex-32-chars>
```

## Deployment

The chart deploys via ArgoCD from the `deploy.yaml` Application manifest.

```bash
# Apply the ArgoCD Application
kubectl apply -f deploy.yaml
```

## Components

| Component | Description |
|-----------|-------------|
| LibreChat | Main chat application (port 3080) |
| MongoDB | Database for conversations and users |
| VaultConnection | VSO connection to Vault |
| VaultAuth | Kubernetes auth method configuration |
| VaultStaticSecret | Syncs secrets from Vault to K8s |
| Policy | VCO policy for Vault access |
| KubernetesAuthEngineRole | VCO role for Kubernetes auth |

## Configuration

### values.yaml

Key configuration options:

```yaml
# AI Endpoints
endpoints:
  anthropic:
    enabled: true
  llamacpp:
    enabled: true
    baseURL: "http://llama-cpp-service.lama.svc.cluster.local:8080/v1"
    models:
      - "llama3"
      - "mistral"

# Service with Tailscale
service:
  annotations:
    tailscale.com/expose: "true"
    tailscale.com/hostname: "chat"
```

### Adding More Models

To add more llama.cpp models, update `values.yaml`:

```yaml
endpoints:
  llamacpp:
    models:
      - "llama3"
      - "mistral"
      - "codellama"
```

## Access

Once deployed, access LibreChat via:

- HTTPRoute: `http://chat.rye`
- Tailscale: `http://chat.tailnet:3080`

## Troubleshooting

### Check pod status
```bash
kubectl get pods -n librechat
kubectl logs -n librechat deployment/librechat
```

### Check Vault secrets sync
```bash
kubectl get vaultstaticsecret -n librechat
kubectl describe vaultstaticsecret -n librechat librechat-anthropic
```

### Check MongoDB
```bash
kubectl logs -n librechat statefulset/librechat-mongodb
```

### Verify secrets exist
```bash
kubectl get secrets -n librechat
```
