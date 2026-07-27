{{/*
FRD Backend Chart 辅助函数
依据：FRD-D10-V1.1 §6.2 Helm Chart 结构
*/}}

{{/*
全限定名：frd-backend
*/}}
{{- define "frd-backend.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
完整应用名（含 release）
*/}}
{{- define "frd-backend.fullname" -}}
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

{{/*
Chart 名称与版本标签
*/}}
{{- define "frd-backend.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
公共标签（依据 D10 §6.3 Helm 标签规范）
*/}}
{{- define "frd-backend.labels" -}}
helm.sh/chart: {{ include "frd-backend.chart" . }}
{{ include "frd-backend.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: fraud-risk-detection
app.kubernetes.io/component: backend
{{- end -}}

{{/*
选择器标签
*/}}
{{- define "frd-backend.selectorLabels" -}}
app.kubernetes.io/name: {{ include "frd-backend.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
命名空间：默认 frd-prod（依据 D10 §6.1）
*/}}
{{- define "frd-backend.namespace" -}}
{{- if .Values.namespace -}}
{{- .Values.namespace -}}
{{- else -}}
{{- .Release.Namespace -}}
{{- end -}}
{{- end -}}

{{/*
镜像全限定名：registry.cn-hangzhou.aliyuncs.com/frd/frd-backend:{tag}
*/}}
{{- define "frd-backend.image" -}}
{{- $registry := .Values.image.registry -}}
{{- $namespace := .Values.image.namespace -}}
{{- $repository := .Values.image.repository -}}
{{- $tag := .Values.image.tag | default .Chart.AppVersion -}}
{{- printf "%s/%s/%s:%s" $registry $namespace $repository $tag -}}
{{- end -}}

{{/*
imagePullSecrets
*/}}
{{- define "frd-backend.imagePullSecrets" -}}
{{- if .Values.imagePullSecrets -}}
imagePullSecrets:
{{- toYaml .Values.imagePullSecrets | nindent 2 }}
{{- end -}}
{{- end -}}
