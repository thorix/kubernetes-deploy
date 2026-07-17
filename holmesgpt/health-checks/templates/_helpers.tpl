{{/*
HolmesGPT health-checks helpers
*/}}

{{/*
Chart fullname - used as prefix for all resource names
*/}}
{{- define "health-checks.fullname" -}}
holmesgpt
{{- end -}}

{{/*
Common labels
*/}}
{{- define "health-checks.labels" -}}
app.kubernetes.io/name: holmesgpt
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}
