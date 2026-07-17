# MCP Gateway

MCP Context-Forge deployment wrapping the [IBM mcp-stack](https://github.com/IBM/mcp-context-forge) Helm chart.

## Vault Secrets Setup

This deployment uses Vault for secrets management. The following secrets must be created in Vault before the VaultStaticSecrets will sync successfully.

### Required Vault Secrets

| Vault Path | Purpose | Required Keys |
|------------|---------|---------------|
| `kv/mcp-gateway/admin` | Admin UI credentials | `PLATFORM_ADMIN_EMAIL`, `PLATFORM_ADMIN_PASSWORD`, `BASIC_AUTH_USER`, `BASIC_AUTH_PASSWORD` |
| `kv/mcp-gateway/database` | PostgreSQL credentials | `POSTGRES_USER`, `POSTGRES_PASSWORD` |
| `kv/mcp-gateway/jwt` | JWT signing key | `JWT_SECRET_KEY` |

### Creating Secrets via CLI

```bash
# Port-forward to Vault (if not using external access)
kubectl port-forward -n vault svc/vault 8200:8200 &

# Set Vault address
export VAULT_ADDR="http://127.0.0.1:8200"

# Login to Vault (use your preferred method)
vault login

# Create admin credentials secret
vault kv put kv/mcp-gateway/admin \
  PLATFORM_ADMIN_EMAIL="admin@example.com" \
  PLATFORM_ADMIN_PASSWORD="$(openssl rand -base64 32)" \
  BASIC_AUTH_USER="admin" \
  BASIC_AUTH_PASSWORD="$(openssl rand -base64 32)"

# Create database credentials secret
vault kv put kv/mcp-gateway/database \
  POSTGRES_USER="mcpgateway" \
  POSTGRES_PASSWORD="$(openssl rand -base64 32)"

# Create JWT secret
vault kv put kv/mcp-gateway/jwt \
  JWT_SECRET_KEY="$(openssl rand -base64 64)"
```

### Secret Key Descriptions

#### Admin Secret (`kv/mcp-gateway/admin`)

| Key | Description |
|-----|-------------|
| `PLATFORM_ADMIN_EMAIL` | Email for the platform admin user |
| `PLATFORM_ADMIN_PASSWORD` | Password for the platform admin user |
| `BASIC_AUTH_USER` | Username for basic auth on admin endpoints |
| `BASIC_AUTH_PASSWORD` | Password for basic auth on admin endpoints |

#### Database Secret (`kv/mcp-gateway/database`)

| Key | Description |
|-----|-------------|
| `POSTGRES_USER` | PostgreSQL username |
| `POSTGRES_PASSWORD` | PostgreSQL password |

#### JWT Secret (`kv/mcp-gateway/jwt`)

| Key | Description |
|-----|-------------|
| `JWT_SECRET_KEY` | Secret key used for signing JWT tokens (should be at least 32 characters) |

## Vault Integration Details

The deployment creates the following Vault resources automatically via vault-config-operator:

- **Policy**: `mcp-gateway` - Grants read access to the secret paths
- **Kubernetes Auth Role**: `mcp-gateway` - Allows the `mcp-gateway` service account to authenticate

### Verifying Vault Setup

```bash
# Check if the Kubernetes auth role exists
vault read auth/kubernetes/role/mcp-gateway

# Check if the policy exists
vault policy read mcp-gateway

# Test reading a secret (after creation)
vault kv get kv/mcp-gateway/admin
```

## Post-Deployment Setup

### Database Bootstrap

After initial deployment, run the database bootstrap to create the admin user and default roles:

```bash
kubectl exec -n mcp-gateway deployment/mcp-gateway-mcpgateway -- \
  sh -c "cd /app && python3 -m mcpgateway.bootstrap_db"
```

This creates:
- Platform admin user (from `PLATFORM_ADMIN_EMAIL` / `PLATFORM_ADMIN_PASSWORD`)
- Default RBAC roles (platform_admin, team_admin, developer, viewer)
- Personal team for the admin user

### Accessing the Admin UI

1. Navigate to `https://mcp.lan/admin` (or your configured hostname)
2. Log in with the platform admin credentials:
   - **Email:** `admin@mcp.gateway` (default)
   - **Password:** `changeme` (default)

## Deployment Notes

### CPU Architecture Requirement

The `ghcr.io/ibm/mcp-context-forge` image (currently `v1.0.0-RC-3`) requires the x86-64-v3 CPU instruction set (Haswell or newer). The deployment is configured with a `nodeSelector` to run on compatible nodes.

### Federation gotchas

- **Tool federation drops on BETA-2:** mcp-context-forge v1.0.0-BETA-2 silently dropped tools whose JSON Schema used free-form objects (e.g., `update_dashboard`'s `dashboard: map[string]interface{}` parameter). RC-3 fixed this via PR [#2342](https://github.com/IBM/mcp-context-forge/pull/2342) — see issue [#4304](https://github.com/IBM/mcp-context-forge/issues/4304). If you upgrade past RC-3, verify federated tool counts haven't regressed.
- **SSRF protection blocks RFC1918 by default (RC-3+):** Set `SSRF_ALLOW_PRIVATE_NETWORKS=true` (configured in `mcpContextForge.config`) so the gateway can reach `*.svc.cluster.local` upstreams. Without this, registration returns 422 *"Gateway URL contains private network address"*.
- **Slow boot under gunicorn preload:** RC-3 with 4 preloaded workers takes longer to bind `/health` than BETA-2. The chart's default exec startup probe (`sleep 10`) doesn't reflect real readiness, so the liveness probe SIGKILLs the pod ~55s in. We override `mcpContextForge.probes.startup` with an HTTP probe on `/health` (failureThreshold 30, periodSeconds 10 = 5 min grace).
- **Alembic runs in-process:** The chart's separate migration Job (`migration.enabled`) is redundant for RC-3+ — it runs migrations on app startup. We keep it disabled because it conflicted with ArgoCD's PreSync hooks.
- **Re-run the registration hook on config change:** The `register-servers` PostSync Job carries a `checksum/servers-config` annotation derived from `mcpServers`/`virtualServers`. Without this, ArgoCD treats values changes as no-ops for the hook and stale gateway registrations linger.

### Default Credentials

If Vault secrets are not configured, the deployment will use default credentials from `values.yaml`. These are insecure and should only be used for initial testing:

- Admin email: `admin@mcp.gateway`
- Admin password: `changeme`
- Basic auth: `admin` / `changeme`
- JWT secret: `change-this-in-production`
- Database: `mcpgateway` / `changeme`

### Services

| Service | Port | Description |
|---------|------|-------------|
| `mcp-gateway-mcpgateway` | 80 | Main MCP Gateway API |
| `mcp-gateway-mcp-fast-time-server` | 80 | MCP Fast Time Server |
| `mcp-gateway-postgres` | 5432 | PostgreSQL database |
| `mcp-gateway-redis` | 6379 | Redis cache |

## Registering MCP Servers (Infrastructure as Code)

MCP servers can be registered automatically via `values.yaml`:

```yaml
mcpServers:
  - name: haystack
    url: "http://haystack-hayhooks.haystack.svc.cluster.local:1417"
    description: "Knowledge base RAG pipelines"
    tags: "rag,knowledge-base"  # optional, comma-separated
  - name: another-server
    url: "http://other-service.namespace.svc.cluster.local:8080"
    description: "Another MCP server"
```

A Helm post-install/post-upgrade hook Job will automatically register these servers with the gateway API after deployment.

**Note:** The target MCP servers must be reachable when the registration job runs. If a server is not yet deployed, the registration will fail for that server but continue for others.

### Accessing the Gateway

The service is exposed via Tailscale with hostname `mcp`. Access the admin UI at:
- Internal: `http://mcp-gateway-mcpgateway.mcp-gateway.svc.cluster.local/admin`
- Tailscale: `http://mcp.{tailnet}/admin`

## Configuring Claude Code

To connect Claude Code to the MCP gateway, you need to generate a JWT token and configure `.mcp.json`.

### Authentication

The SSE endpoint (`/sse`) requires **JWT Bearer token** authentication. Basic Auth only works for admin endpoints, not for MCP client connections.

### Generating a Long-Lived JWT Token

Generate a JWT token with a 1-year expiry (525600 minutes):

```bash
kubectl exec -n mcp-gateway deployment/mcp-gateway-mcpgateway -- \
  python3 -m mcpgateway.utils.create_jwt_token \
  --username "admin@mcp.gateway" \
  --exp 525600
```

This outputs a JWT token that you'll use in your `.mcp.json` configuration.

**Token options:**
- `--username`: The user email (must exist in the system)
- `--exp`: Expiration in minutes (525600 = 1 year, 0 = never expires)

### Setup Steps

1. **Generate a JWT token** (see above)

2. **Create `.mcp.json`** in the repository root:
   ```json
   {
     "mcpServers": {
       "mcp-gateway": {
         "type": "sse",
         "url": "https://mcp.lan/sse",
         "headers": {
           "Authorization": "Bearer <YOUR_JWT_TOKEN>"
         }
       }
     }
   }
   ```

3. **Restart Claude Code** (or start a new session) to load the MCP configuration

4. **Verify connection** by running `/mcp` in Claude Code - you should see `mcp-gateway` listed

### Available Tools

The MCP gateway provides access to tools from registered gateways. Currently configured:

| Tool | Description |
|------|-------------|
| `haystack-deploy-pipeline` | Deploy a pipeline from files |
| `haystack-undeploy-pipeline` | Undeploy/remove a pipeline |
| `haystack-get-pipeline-status` | Get status of a specific pipeline |
| `haystack-get-all-pipeline-statuses` | Get status of all pipelines |

### Troubleshooting

- **No MCP servers listed**: Ensure you've restarted Claude Code after adding `.mcp.json`
- **Connection refused**: Verify the gateway is running with `curl https://mcp.lan/health`
- **401 Unauthorized / "Authorization token required"**: The SSE endpoint requires a JWT Bearer token, not Basic Auth. Generate a new token using the command above.
- **Token expired**: Generate a new token with a longer expiry using `--exp 525600` (1 year) or `--exp 0` (never expires)
- **Tools not available**: Verify the Haystack gateway is registered via the Admin UI at `https://mcp.lan/admin`
