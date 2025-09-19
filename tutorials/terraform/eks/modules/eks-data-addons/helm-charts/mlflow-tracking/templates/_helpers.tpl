{{/*
Expand the name of the chart.
*/}}
{{- define "mlflow-tracking-server.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "mlflow-tracking-server.fullname" -}}
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
{{- define "mlflow-tracking-server.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "mlflow-tracking-server.labels" -}}
helm.sh/chart: {{ include "mlflow-tracking-server.chart" . }}
{{ include "mlflow-tracking-server.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "mlflow-tracking-server.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mlflow-tracking-server.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "mlflow-tracking-server.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "mlflow-tracking-server.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Database uri
*/}}
{{- define "mlflow.database.uri" -}}
{{- printf "postgresql+psycopg2://%s:%s@%s:%v/%s" .Values.mlflow.database.username .Values.mlflow.database.password .Values.mlflow.database.host .Values.mlflow.database.port .Values.mlflow.database.name }}
{{- end}}
