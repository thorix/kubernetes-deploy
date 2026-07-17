{{/*
Expand the name of the chart.
*/}}
{{- define "haystack.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "haystack.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "haystack.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "haystack.labels" -}}
helm.sh/chart: {{ include "haystack.chart" . }}
{{ include "haystack.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "haystack.selectorLabels" -}}
app.kubernetes.io/name: {{ include "haystack.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app: {{ include "haystack.name" . }}
{{- end }}

{{/*
Hayhooks specific labels
*/}}
{{- define "haystack.hayhooksLabels" -}}
{{ include "haystack.labels" . }}
app.kubernetes.io/component: hayhooks
{{- end }}

{{/*
Hayhooks selector labels
*/}}
{{- define "haystack.hayhooksSelectorLabels" -}}
{{ include "haystack.selectorLabels" . }}
app.kubernetes.io/component: hayhooks
{{- end }}
