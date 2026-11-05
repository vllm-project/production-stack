{{/*
Expand the name of the chart.
*/}}
{{- define "vllm-stack-operator.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "vllm-stack-operator.fullname" -}}
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
Common labels
*/}}
{{- define "vllm-stack-operator.labels" -}}
helm.sh/chart: {{ include "vllm-stack-operator.name" . }}-{{ .Chart.Version | replace "+" "_" }}
{{ include "vllm-stack-operator.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "vllm-stack-operator.selectorLabels" -}}
app.kubernetes.io/name: {{ include "vllm-stack-operator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: operator
{{- end }}

{{/*
Name of the service account to use
*/}}
{{- define "vllm-stack-operator.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "vllm-stack-operator.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Label key placed on every VLLMRuntime rendered by this chart. The operator
copies CR labels onto the engine pods, and the router's k8sLabelSelector
defaults to this label so one router serves every runtime (model) of the
release.
*/}}
{{- define "vllm-stack-operator.runtimeSetLabelKey" -}}
production-stack.vllm.ai/runtime-set
{{- end }}

{{/*
Name of the VLLMRuntime custom resource for a given array entry.
Params: dict (root - $, i - index, rt - entry).
Entry 0 defaults to "<fullname>-runtime"; entry i>0 to "<fullname>-runtime-<i>".
Kept within 63 characters because the operator derives the engine Service name
and the `app=<name>` pod label value from it — both are limited to 63 chars.
*/}}
{{- define "vllm-stack-operator.runtimeResourceName" -}}
{{- $base := include "vllm-stack-operator.fullname" .root | trunc 55 | trimSuffix "-" -}}
{{- $name := printf "%s-runtime" $base -}}
{{- if gt (int .i) 0 -}}
{{- $name = printf "%s-runtime-%d" ($base | trunc 52 | trimSuffix "-") (int .i) -}}
{{- end -}}
{{- default $name .rt.name | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{/*
Name of the VLLMRouter custom resource. Kept within 63 characters (accounting
for the suffix) because the operator derives the router Service name from it.
*/}}
{{- define "vllm-stack-operator.routerName" -}}
{{- default (printf "%s-router" (include "vllm-stack-operator.fullname" . | trunc 56 | trimSuffix "-")) .Values.vllmRouter.name | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{/*
Name of the CacheServer custom resource. Kept within 63 characters (accounting
for the suffix) because the operator derives the cache server Service name from it.
*/}}
{{- define "vllm-stack-operator.cacheServerName" -}}
{{- default (printf "%s-cacheserver" (include "vllm-stack-operator.fullname" . | trunc 51 | trimSuffix "-")) .Values.cacheServer.name | trunc 63 | trimSuffix "-" -}}
{{- end }}

