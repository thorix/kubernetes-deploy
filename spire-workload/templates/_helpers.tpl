{{/*
Common labels for the wrapper's own resources (Vault wiring, bundle endpoint).
*/}}
{{- define "spire-wrapper.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Name of the upstream CA Secret. Single source of truth: the subchart's
upstreamAuthority.disk.secret.name, so the VSO destination and the server mount
can never disagree.
*/}}
{{- define "spire-wrapper.upstreamCASecret" -}}
{{- index .Values.spire "spire-server" "upstreamAuthority" "disk" "secret" "name" -}}
{{- end }}
