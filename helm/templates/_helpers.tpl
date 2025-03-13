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
{{      toYaml . }}
{{-   end }}
{{- end }}


{{/*
Define liveness et readiness probes
*/}}
{{- define "chart.probes" -}}
{{-   if .Values.servingEngineSpec.startupProbe  }}
startupProbe:
{{-     with .Values.servingEngineSpec.startupProbe }}
{{-       toYaml . | nindent 2 }}
{{-     end }}
{{-   end }}
{{-   if .Values.servingEngineSpec.livenessProbe  }}
livenessProbe:
{{-     with .Values.servingEngineSpec.livenessProbe }}
{{-       toYaml . | nindent 2 }}
{{-     end }}
{{-   end }}
{{- end }}

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
{{- if or (hasKey $modelSpec "limitMemory") (hasKey $modelSpec "limitCPU") (gt (int $modelSpec.requestGPU) 0) }}
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
