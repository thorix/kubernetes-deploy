# simple-service

A reusable Helm library chart for deploying simple Kubernetes services.

## Overview

This is a **library chart** that provides common templates for:
- Deployment with configurable containers, probes, and resources
- Service (ClusterIP by default)
- HTTPRoute (Gateway API)
- ServiceAccount
- ConfigMap for environment/configuration

## Usage

### 1. Add as Dependency

In your chart's `Chart.yaml`:

```yaml
apiVersion: v2
name: my-app
version: 1.0.0
dependencies:
  - name: simple-service
    version: "^1.0.0"
    repository: "oci://ghcr.io/YOUR_ORG/charts"
```

Run `helm dependency update` to fetch the chart.

### 2. Include Templates

Create a single template file (e.g., `templates/all.yaml`):

```yaml
{{- include "simple-service.all" . }}
```

Or include individual components:

```yaml
{{- include "simple-service.deployment" . }}
---
{{- include "simple-service.service" . }}
```

### 3. Configure via values.yaml

```yaml
# Image configuration
image:
  repository: my-app
  tag: "1.0.0"

# Container port
containerPort: 8080

# Enable HTTPRoute
httproute:
  enabled: true
  hostname: my-app.lan

# Resources
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi
```

## Available Templates

| Template | Description |
|----------|-------------|
| `simple-service.all` | Renders all resources |
| `simple-service.deployment` | Deployment resource |
| `simple-service.service` | Service resource |
| `simple-service.httproute` | HTTPRoute resource |
| `simple-service.serviceaccount` | ServiceAccount resource |
| `simple-service.configmap` | ConfigMap resource |

## Configuration

### Core Settings

| Parameter | Description | Default |
|-----------|-------------|---------|
| `image.repository` | Container image repository | `nginx` |
| `image.tag` | Container image tag | `latest` |
| `image.pullPolicy` | Image pull policy | `IfNotPresent` |
| `replicaCount` | Number of replicas | `1` |
| `containerPort` | Container port | `8080` |

### Service

| Parameter | Description | Default |
|-----------|-------------|---------|
| `service.enabled` | Enable service | `true` |
| `service.type` | Service type | `ClusterIP` |
| `service.port` | Service port | `80` |
| `service.targetPort` | Target port (defaults to containerPort) | `""` |
| `service.annotations` | Service annotations | `{}` |

### HTTPRoute

| Parameter | Description | Default |
|-----------|-------------|---------|
| `httproute.enabled` | Enable HTTPRoute | `false` |
| `httproute.hostname` | Hostname for routing | `""` |
| `httproute.gateway.name` | Gateway name | `https-gateway` |
| `httproute.gateway.namespace` | Gateway namespace | `kube-system` |

### Probes

| Parameter | Description | Default |
|-----------|-------------|---------|
| `probes.enabled` | Enable liveness/readiness probes | `true` |
| `probes.liveness.path` | Liveness probe path | `/` |
| `probes.readiness.path` | Readiness probe path | `/` |

### ConfigMap

| Parameter | Description | Default |
|-----------|-------------|---------|
| `configMap.enabled` | Enable ConfigMap | `false` |
| `configMap.data` | Key-value pairs for env vars | `{}` |
| `configMap.mountPath` | Mount as files at this path | `""` |
| `configMap.files` | File contents (when mountPath set) | `{}` |

### Vault Integration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `vault.enabled` | Enable Vault integration | `false` |
| `vault.address` | Vault server address | `http://vault.vault.svc.cluster.local:8200` |
| `vault.skipTLSVerify` | Skip TLS verification | `true` |
| `vault.mount` | KV secrets engine mount | `kv` |
| `vault.refreshAfter` | Secret refresh interval | `1h` |
| `vault.kubernetes.mountPath` | Kubernetes auth mount path | `kubernetes` |
| `vault.kubernetes.role` | Vault role name | `<release-name>` |
| `vault.kubernetes.serviceAccount` | Service account for auth | `<chart-service-account>` |
| `vault.kubernetes.audience` | JWT audience | `vault` |
| `vault.kubernetes.tokenTTL` | Token TTL in seconds | `86400` |
| `vault.secrets` | Map of secrets to sync | `{}` |

When `vault.enabled: true` and `vault.secrets` is configured, the chart creates:
- VaultConnection - connection to Vault server
- VaultAuth - Kubernetes authentication configuration
- VaultStaticSecret - one per entry in `vault.secrets`
- Policy - Vault policy with read permissions
- KubernetesAuthEngineRole - Vault role binding

### Advanced

| Parameter | Description | Default |
|-----------|-------------|---------|
| `env` | Additional environment variables | `[]` |
| `envFrom` | Environment from secrets/configmaps | `[]` |
| `volumes` | Additional volumes | `[]` |
| `volumeMounts` | Additional volume mounts | `[]` |
| `extraContainers` | Sidecar containers | `[]` |
| `initContainers` | Init containers | `[]` |
| `nodeSelector` | Node selector | `{}` |
| `tolerations` | Tolerations | `[]` |
| `affinity` | Affinity rules | `{}` |

## Examples

### Minimal Deployment

```yaml
# values.yaml
image:
  repository: nginx
  tag: "1.25-alpine"
containerPort: 80
```

### With HTTPRoute and ConfigMap

```yaml
# values.yaml
image:
  repository: my-app
  tag: "2.0.0"

containerPort: 3000

httproute:
  enabled: true
  hostname: app.lan

configMap:
  enabled: true
  data:
    LOG_LEVEL: "info"
    API_URL: "https://api.lan"
```

### With Vault Secrets Integration

```yaml
# values.yaml
image:
  repository: my-app
  tag: "1.0.0"

# Enable Vault integration
vault:
  enabled: true
  secrets:
    config: "myapp/config"        # Creates secret: myapp-config
    credentials: "myapp/creds"    # Creates secret: myapp-credentials

# Use the synced secrets
envFrom:
  - secretRef:
      name: my-app-simple-service-config
  - secretRef:
      name: my-app-simple-service-credentials
```

This automatically creates:
- VaultConnection for connecting to Vault
- VaultAuth for Kubernetes authentication
- Policy with read permissions for the specified paths
- KubernetesAuthEngineRole for the service account
- VaultStaticSecret resources that sync secrets to Kubernetes

## Versioning

This chart follows semantic versioning:
- **MAJOR**: Breaking changes to values structure
- **MINOR**: New features, backwards compatible
- **PATCH**: Bug fixes

Use version ranges in dependencies:
- `^1.0.0` - Any 1.x.x version (recommended)
- `~1.0.0` - Only 1.0.x versions
- `1.0.0` - Exact version
