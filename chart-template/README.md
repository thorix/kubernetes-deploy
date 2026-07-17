# Chart Template

> **Recommended**: For new deployments, prefer using the `simple-service` base chart instead of copying these templates. See [simple-service README](../simple-service/README.md) for details.

## Using simple-service (Recommended)

The `simple-service/` chart provides a reusable base for deployments with these benefits:
- Less code duplication
- Centralized feature additions (network policies, etc.)
- Versioned updates via semver
- Null-safe value handling

### Quick Start

1. Create chart with dependency:

```yaml
# Chart.yaml
apiVersion: v2
name: my-app
version: 1.0.0
dependencies:
  - name: simple-service
    version: "^1.0.0"
    repository: "file://../simple-service"  # or OCI after publishing
```

2. Create `templates/main.yaml`:

```yaml
{{- include "simple-service.deployment" . }}
---
{{- include "simple-service.service" . }}
---
{{- include "simple-service.httproute" . }}
---
{{- include "simple-service.serviceaccount" . }}
```

3. Configure `values.yaml`:

```yaml
image:
  repository: my-app
  tag: "1.0.0"
containerPort: 8080
```

4. Configure `values.prod.yaml`:

```yaml
httproute:
  enabled: true
  hostname: my-app.lan
  gateway:
    name: https-gateway
    namespace: kube-system
```

5. Build and verify:

```bash
helm dependency update ./my-app
helm template my-app ./my-app -f values.yaml -f values.prod.yaml
```

See `../ai-knowledge-base/kubernetes/simple-service-chart.md` for full documentation.

---

## Legacy Template (This Directory)

Copy this template only for charts that need features not yet in simple-service (like Vault integration):

```bash
# Copy template to new chart
cp -r chart-template myapp

# Update Chart.yaml name and description
# Create deploy.yaml for ArgoCD
# Update values.yaml (search CHANGEME)
# Create values.prod.yaml with hostname
```

### Included Patterns

| File | Purpose |
|------|---------|
| `deployment.yaml` | App deployment with health probes |
| `service.yaml` | ClusterIP service with annotations |
| `httproute.yaml` | Gateway API HTTPRoute |
| `pvc.yaml` | Optional persistent storage |
| `vault-*.yaml` | Full Vault integration (5 files) |

### Disabling Features

```yaml
vault:
  enabled: false

httproute:
  enabled: false

persistence:
  enabled: false
```

### Adding Environment Variables from Vault

Edit `deployment.yaml` to inject secrets:

```yaml
env:
  - name: API_KEY
    valueFrom:
      secretKeyRef:
        name: {{ include "app.fullname" . }}-app
        key: api-key
```
