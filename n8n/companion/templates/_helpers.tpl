{{/*
n8n companion chart helpers
*/}}

{{/*
Chart fullname - used as prefix for all resource names
*/}}
{{- define "companion.fullname" -}}
n8n
{{- end -}}

{{/*
Common labels
*/}}
{{- define "companion.labels" -}}
app.kubernetes.io/name: n8n
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}
