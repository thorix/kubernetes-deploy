# envoy-gateway-crds

Installs only the Envoy Gateway CRDs (`*.gateway.envoyproxy.io`) from the
`gateway-crds-helm` chart (v1.9.3). The Gateway API CRDs
(`gateway.networking.k8s.io`) are owned by another app. This chart must never
render or change them: a CRD version mismatch silently kills ingress.

`crds.gatewayAPI.enabled: false` and `crds.envoyGateway.enabled: true` are the
real keys in the chart's `values.yaml`. Re-run the guard on every chart bump.

## Render guard

```sh
helm template x oci://docker.io/envoyproxy/gateway-crds-helm --version v1.9.3 \
  -f envoy-gateway-crds/values.yaml > /tmp/r.yaml

# 1. Only CustomResourceDefinition objects
grep -E '^kind:' /tmp/r.yaml | sort | uniq -c
#   8 kind: CustomResourceDefinition

# 2. Every CRD is in group gateway.envoyproxy.io (expect 8 / 0)
grep -cE '^  name: .*\.gateway\.envoyproxy\.io$' /tmp/r.yaml
grep -E '^  name:' /tmp/r.yaml | grep -vc 'gateway.envoyproxy.io$'
grep -E '^  group:' /tmp/r.yaml | sort | uniq -c
#   8 group: gateway.envoyproxy.io

# 3. No ValidatingAdmissionPolicy (expect 0)
grep -c ValidatingAdmissionPolicy /tmp/r.yaml

# 4. Mentions of the Gateway API group are schema text only (82 at v1.9.3:
#    field descriptions, defaults, CEL rules inside EG CRDs). No metadata.name
#    or spec.group uses it, as checks 1-2 show.
grep -c 'gateway.networking.k8s.io' /tmp/r.yaml
```

Sensitivity check: adding `--set crds.gatewayAPI.enabled=true` makes check 2
fail (renders `gatewayclasses.gateway.networking.k8s.io` and others).
