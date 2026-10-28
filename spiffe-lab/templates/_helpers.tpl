{{/*
Common labels. Call with (dict "root" $ "name" <component>).
*/}}
{{- define "spiffe-lab.labels" -}}
helm.sh/chart: {{ .root.Chart.Name }}-{{ .root.Chart.Version }}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/part-of: spiffe-lab
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
{{- end }}

{{/*
SPIFFE ID from the lab template. Call with (dict "td" <trust domain> "ns" <namespace> "sa" <serviceaccount>).
*/}}
{{- define "spiffe-lab.id" -}}
{{- printf "spiffe://%s/ns/%s/sa/%s" .td .ns .sa -}}
{{- end }}

{{- define "spiffe-lab.serverID" -}}
{{- include "spiffe-lab.id" (dict "td" .Values.trustDomains.infra "ns" .Values.server.namespace "sa" .Values.server.serviceAccount) -}}
{{- end }}

{{- define "spiffe-lab.clientID" -}}
{{- include "spiffe-lab.id" (dict "td" .Values.trustDomains.workload "ns" .Values.client.namespace "sa" .Values.client.serviceAccount) -}}
{{- end }}

{{- define "spiffe-lab.image" -}}
{{- printf "%s:%s" .Values.image.repository (required "image.tag is required (<git-sha>@sha256:<digest>)" .Values.image.tag) -}}
{{- end }}

{{/*
Pod-level settings shared by every lab pod (PSS restricted).
*/}}
{{- define "spiffe-lab.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 65532
runAsGroup: 65532
seccompProfile:
  type: RuntimeDefault
{{- end }}

{{- define "spiffe-lab.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: [ALL]
{{- end }}

{{- define "spiffe-lab.podAnnotations" -}}
prometheus.io/scrape: "true"
prometheus.io/port: "9090"
prometheus.io/path: /metrics
{{- end }}

{{/*
Probes on the ops listener. The listener starts only after the first SVID
arrives, so the startup probe allows time for entry creation.
*/}}
{{- define "spiffe-lab.probes" -}}
startupProbe:
  httpGet:
    path: /healthz
    port: ops
  periodSeconds: 5
  failureThreshold: 60
readinessProbe:
  httpGet:
    path: /healthz
    port: ops
  periodSeconds: 10
  failureThreshold: 3
livenessProbe:
  httpGet:
    path: /healthz
    port: ops
  periodSeconds: 20
  failureThreshold: 6
{{- end }}

{{/*
Workload API volume mount and env. Call with the root context.
*/}}
{{- define "spiffe-lab.workloadAPIMount" -}}
- name: spiffe-workload-api
  mountPath: {{ .Values.workloadAPI.mountPath }}
  readOnly: true
{{- end }}

{{/*
CSI volume for one trust domain. Call with (dict "driver" <csi driver name>).
*/}}
{{- define "spiffe-lab.workloadAPIVolume" -}}
- name: spiffe-workload-api
  csi:
    driver: {{ .driver }}
    readOnly: true
{{- end }}
