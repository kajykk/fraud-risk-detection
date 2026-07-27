{{/*
FRD ML Chart 辅助函数（ML + GNN 合并）
*/}}

{{- define "frd-ml.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "frd-ml.fullname" -}}
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

{{- define "frd-ml.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "frd-ml.labels" -}}
helm.sh/chart: {{ include "frd-ml.chart" . }}
{{ include "frd-ml.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: fraud-risk-detection
app.kubernetes.io/component: ml-gnn
{{- end -}}

{{- define "frd-ml.selectorLabels" -}}
app.kubernetes.io/name: {{ include "frd-ml.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "frd-ml.namespace" -}}
{{- if .Values.namespace -}}
{{- .Values.namespace -}}
{{- else -}}
{{- .Release.Namespace -}}
{{- end -}}
{{- end -}}

{{- define "frd-ml.image-ml" -}}
{{- printf "%s/%s/%s:%s" .Values.image.registry .Values.image.namespace .Values.image.mlRepository .Values.image.tag -}}
{{- end -}}

{{- define "frd-ml.image-gnn" -}}
{{- printf "%s/%s/%s:%s" .Values.image.registry .Values.image.namespace .Values.image.gnnRepository .Values.image.tag -}}
{{- end -}}
