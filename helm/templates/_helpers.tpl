{{/*
Define ports for the pods
*/}}
{{- define "chart.container-port" -}}
{{-  default "8000" .Values.servingEngineSpec.containerPort }}
{{- end }}

{{/*
Define service port
*/}}
{{- define "chart.service-port" -}}
{{-  if .Values.servingEngineSpec.servicePort }}
{{-    .Values.servingEngineSpec.servicePort }}
{{-  else }}
{{-    include "chart.container-port" . }}
{{-  end }}
{{- end }}

{{/*
Define service port name
*/}}
{{- define "chart.service-port-name" -}}
"service-port"
{{- end }}

{{/*
Define container port name
*/}}
{{- define "chart.container-port-name" -}}
"container-port"
{{- end }}

{{/*
Define engine deployment strategy.
If .Values.engineStrategy is defined, use it.
Otherwise, fall back to the default rolling update strategy.
*/}}
{{- define "chart.engineStrategy" -}}
strategy:
{{- if .Values.servingEngineSpec.strategy }}
{{- toYaml .Values.servingEngineSpec.strategy | nindent 2 }}
{{- else }}
  rollingUpdate:
    maxSurge: 100%
    maxUnavailable: 0
{{- end }}
{{- end }}

{{/*
Define router deployment strategy.
If .Values.routerStrategy is defined, use it.
Otherwise, fall back to the default rolling update strategy.
*/}}
{{- define "chart.routerStrategy" -}}
strategy:
{{- if .Values.routerSpec.strategy }}
{{- toYaml .Values.routerSpec.strategy | nindent 2 }}
{{- else }}
  rollingUpdate:
    maxSurge: 100%
    maxUnavailable: 0
{{- end }}
{{- end }}

{{/*
Define additional ports
*/}}
{{- define "chart.extraPorts" }}
{{-   with .Values.servingEngineSpec.extraPorts }}
{{-     toYaml . }}
{{-   end }}
{{- end }}

{{/*
Define additional router ports
*/}}
{{- define "chart.routerExtraPorts" }}
{{-   with .Values.routerSpec.extraPorts }}
{{-     toYaml . }}
{{-   end }}
{{- end }}

{{/*
Define startup, liveness and readiness probes
*/}}
{{- define "chart.templateProbe"}}
  initialDelaySeconds: {{ .initialDelaySeconds | default 15 }}
  periodSeconds: {{ .periodSeconds | default 10 }}
  failureThreshold: {{ .failureThreshold | default 3 }}
  {{- if .timeoutSeconds }}
  timeoutSeconds: {{ .timeoutSeconds }}
  {{- end }}
  {{- if .successThreshold }}
  successThreshold: {{ .successThreshold }}
  {{- end }}
  {{- if .exec }}
  exec:
    command: {{- range .exec.command }}
      - {{. | quote }} {{- end}}
  {{- else if .tcpSocket }}
  tcpSocket:
    {{- if .tcpSocket.host }}
    host: {{ .tcpSocket.host }}
    {{- end }}
    port: {{ .tcpSocket.port }}
  {{- else if .grpc }}
  grpc:
    {{- if .grpc.service }}
    service: {{ .grpc.service }}
    {{- end }}
    port: {{ .grpc.port }}
  {{- else }}
  httpGet:
    path:  {{ .httpGet.path | default "/health" }}
    port: {{ .httpGet.port | default 8000 }}
    {{- if .httpGet.httpHeaders }}
    httpHeaders: {{- range .httpGet.httpHeaders }}
      - name: {{ .name }}
        value: {{ .value | quote }}
    {{- end }}
    {{- end }}
    {{- if .httpGet.host }}
    host: {{ .httpGet.host }}
    {{- end }}
    {{- if .httpGet.scheme }}
    scheme: {{ .httpGet.scheme }}
    {{- end }}
  {{- end }}
{{- end }}
{{- define "chart.probes" -}}
{{- if .Values.servingEngineSpec.startupProbe }}
startupProbe:
  {{- with .Values.servingEngineSpec.startupProbe }}
  {{- include "chart.templateProbe" . }}
  {{- end }}
{{- end }}
{{- if .Values.servingEngineSpec.livenessProbe }}
livenessProbe:
  {{- with .Values.servingEngineSpec.livenessProbe }}
  {{- include "chart.templateProbe" . }}
  {{- end }}
{{- end }}
{{- if .Values.servingEngineSpec.readinessProbe }}
readinessProbe:
  {{- with .Values.servingEngineSpec.readinessProbe }}
  {{- include "chart.templateProbe" . }}
  {{- end }}
{{- end }}

{{- end }}

{{- define "chart.hasLimits" -}}
{{- $modelSpec := . -}}
{{- or
    (hasKey $modelSpec "limitMemory")
    (hasKey $modelSpec "limitCPU")
    (gt (int $modelSpec.requestGPU) 0)
    (hasKey $modelSpec "limitGPUMem")
    (hasKey $modelSpec "limitGPUMemPercentage")
    (hasKey $modelSpec "limitGPUCores")
-}}
{{- end -}}

{{/*
Define resources with a variable model spec
*/}}
{{- define "chart.resources" -}}
{{- $modelSpec := . -}}
requests:
  memory: {{ required "Value 'modelSpec.requestMemory' must be defined !" ($modelSpec.requestMemory | quote) }}
  cpu: {{ required "Value 'modelSpec.requestCPU' must be defined !" ($modelSpec.requestCPU | quote) }}
  {{- if (gt (int $modelSpec.requestGPU) 0) }}
  {{- $gpuType := default "nvidia.com/gpu" $modelSpec.requestGPUType }}
  {{ $gpuType }}: {{ required "Value 'modelSpec.requestGPU' must be defined !" (index $modelSpec.requestGPU | quote) }}
  {{- end }}
  {{- if (hasKey $modelSpec "requestGPUMem") }}
  nvidia.com/gpumem: {{ $modelSpec.requestGPUMem | quote }}
  {{- end }}
  {{- if (hasKey $modelSpec "requestGPUMemPercentage") }}
  nvidia.com/gpumem-percentage: {{ $modelSpec.requestGPUMemPercentage | quote }}
  {{- end }}
  {{- if (hasKey $modelSpec "requestGPUCores") }}
  nvidia.com/gpucores: {{ $modelSpec.requestGPUCores | quote }}
  {{- end }}
{{- if (include "chart.hasLimits" $modelSpec | fromYaml) }}
limits:
  {{- if (hasKey $modelSpec "limitMemory") }}
  memory: {{ $modelSpec.limitMemory | quote }}
  {{- end }}
  {{- if (hasKey $modelSpec "limitCPU") }}
  cpu: {{ $modelSpec.limitCPU | quote }}
  {{- end }}
  {{- if (gt (int $modelSpec.requestGPU) 0) }}
  {{- $gpuType := default "nvidia.com/gpu" $modelSpec.requestGPUType }}
  {{ $gpuType }}: {{ required "Value 'modelSpec.requestGPU' must be defined !" (index $modelSpec.requestGPU | quote) }}
  {{- end }}
  {{- if (hasKey $modelSpec "limitGPUMem") }}
  nvidia.com/gpumem: {{ $modelSpec.limitGPUMem | quote }}
  {{- end }}
  {{- if (hasKey $modelSpec "limitGPUMemPercentage") }}
  nvidia.com/gpumem-percentage: {{ $modelSpec.limitGPUMemPercentage | quote }}
  {{- end }}
  {{- if (hasKey $modelSpec "limitGPUCores") }}
  nvidia.com/gpucores: {{ $modelSpec.limitGPUCores | quote }}
  {{- end }}
{{- end }}
{{- end }}

{{/*
  Define labels for serving engine and its service
*/}}
{{- define "chart.engineLabels" -}}
{{-   with .Values.servingEngineSpec.labels -}}
{{      toYaml . }}
{{-   end }}
{{- end }}

{{/*
  Define labels for router and its service
*/}}
{{- define "chart.routerLabels" -}}
{{-   with .Values.routerSpec.labels -}}
{{      toYaml . }}
{{-   end }}
{{- end }}

{{/*
  Define labels for cache server and its service
*/}}
{{- define "chart.cacheserverLabels" -}}
{{-   with .Values.cacheserverSpec.labels -}}
{{      toYaml . }}
{{-   end }}
{{- end }}

{{/*
  Define helper function to convert labels to a comma separated list
*/}}
{{- define "labels.toCommaSeparatedList" -}}
{{- $labels := . -}}
{{- $result := "" -}}
{{- range $key, $value := $labels -}}
  {{- if $result }},{{ end -}}
  {{ $key }}={{ $value }}
  {{- $result = "," -}}
{{- end -}}
{{- end -}}


{{/*
  Define helper function to format remote cache url
*/}}
{{- define "cacheserver.formatRemoteUrl" -}}
lm://{{ .service_name }}:{{ .port }}
{{- end -}}

{{/*
  Define common Kubernetes labels for every model listed in modelSpec, which is a subset of standard labels without modelName
  Usage: include "chart.engineCommonLabels" (dict "releaseName" .Release.Name "chartName" .Chart.Name)
*/}}
{{- define "chart.engineCommonLabels" -}}
app.kubernetes.io/instance: {{ .releaseName }}
app.kubernetes.io/component: serving-engine
app.kubernetes.io/part-of: {{ .chartName }}
app.kubernetes.io/managed-by: helm
{{- end -}}

{{/*
  Define standard Kubernetes labels for serving engine
  Usage: include "chart.engineStandardLabels" (dict "releaseName" .Release.Name "modelName" $modelSpec.name "chartName" .Chart.Name)
*/}}
{{- define "chart.engineStandardLabels" -}}
app.kubernetes.io/name: {{ .modelName }}
{{- include "chart.engineCommonLabels" . | nindent 0 }}
{{- end -}}

{{/*
  Define standard Kubernetes labels for router
  Usage: include "chart.routerStandardLabels" (dict "releaseName" .Release.Name "chartName" .Chart.Name)
*/}}
{{- define "chart.routerStandardLabels" -}}
app.kubernetes.io/name: router
app.kubernetes.io/instance: {{ .releaseName }}
app.kubernetes.io/component: router
app.kubernetes.io/part-of: {{ .chartName }}
app.kubernetes.io/managed-by: helm
{{- end -}}

{{/*
  Define standard Kubernetes labels for cache server
  Usage: include "chart.cacheserverStandardLabels" (dict "releaseName" .Release.Name "chartName" .Chart.Name)
*/}}
{{- define "chart.cacheserverStandardLabels" -}}
app.kubernetes.io/name: cache-server
app.kubernetes.io/instance: {{ .releaseName }}
app.kubernetes.io/component: cache-server
app.kubernetes.io/part-of: {{ .chartName }}
app.kubernetes.io/managed-by: helm
{{- end -}}
