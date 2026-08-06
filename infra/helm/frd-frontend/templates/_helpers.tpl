{{/*
FRD Frontend Chart 辅助函数
*/}}

{{- define "frd-frontend.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "frd-frontend.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "frd-frontend.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "frd-frontend.labels" -}}
helm.sh/chart: {{ include "frd-frontend.chart" . }}
{{ include "frd-frontend.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: fraud-risk-detection
app.kubernetes.io/component: frontend
{{- end -}}

{{- define "frd-frontend.selectorLabels" -}}
app.kubernetes.io/name: {{ include "frd-frontend.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "frd-frontend.namespace" -}}
{{- if .Values.namespace -}}
{{- .Values.namespace -}}
{{- else -}}
{{- .Release.Namespace -}}
{{- end -}}
{{- end -}}

{{- define "frd-frontend.image" -}}
{{- $registry := .Values.image.registry -}}
{{- $namespace := .Values.image.namespace -}}
{{- $repository := .Values.image.repository -}}
{{- $tag := .Values.image.tag | default .Chart.AppVersion -}}
{{- printf "%s/%s/%s:%s" $registry $namespace $repository $tag -}}
{{- end -}}

{{- define "frd-frontend.serviceAccountName" -}}
{{- if .Values.serviceAccount.name -}}
{{- .Values.serviceAccount.name -}}
{{- else -}}
{{- printf "%s-sa" (include "frd-frontend.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
