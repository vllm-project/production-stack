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

{{/*
  Validate DRA configuration for a model spec. Fails the render with an
  actionable message on conflicting or incomplete DRA settings.
  Call with: include "chart.draCheck" $modelSpec
*/}}
{{- define "chart.draCheck" -}}
{{- if eq (.gpuAllocation | default "device-plugin") "dra" -}}
{{- if and (hasKey . "requestGPU") (ne (toString .requestGPU) "") -}}
{{- if gt (int .requestGPU) 0 -}}
{{- fail (printf "modelSpec '%s': gpuAllocation 'dra' cannot be combined with requestGPU. Remove requestGPU; GPUs are allocated via DRA claims (ResourceClaimTemplate)" .name) -}}
{{- end -}}
{{- end -}}
{{- if or (hasKey . "requestGPUMem") (hasKey . "requestGPUMemPercentage") (hasKey . "requestGPUCores") -}}
{{- fail (printf "modelSpec '%s': gpuAllocation 'dra' cannot be combined with HAMi GPU requests (requestGPUMem, requestGPUMemPercentage, requestGPUCores)" .name) -}}
{{- end -}}
{{- if .resources -}}
{{- $hasClaim := false -}}
{{- if hasKey .resources "claims" -}}
{{- range .resources.claims -}}
{{- if eq .name "gpu" -}}
{{- $hasClaim = true -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- if not $hasClaim -}}
{{- fail (printf "modelSpec '%s': gpuAllocation 'dra' with a custom 'resources' block requires a 'claims' entry with name 'gpu'" .name) -}}
{{- end -}}
{{- end -}}
{{- if and (hasKey . "raySpec") (hasKey .raySpec "enabled") .raySpec.enabled -}}
{{- $hn := default dict .raySpec.headNode -}}
{{- if and (hasKey $hn "requestGPU") (ne (toString $hn.requestGPU) "") -}}
{{- if gt (int $hn.requestGPU) 0 -}}
{{- fail (printf "modelSpec '%s': gpuAllocation 'dra' cannot be combined with raySpec.headNode.requestGPU. Set raySpec.headNode.requestGPU to 0; GPUs are allocated via DRA claims (ResourceClaimTemplate)" .name) -}}
{{- end -}}
{{- end -}}
{{- if or (hasKey $hn "requestGPUMem") (hasKey $hn "requestGPUMemPercentage") (hasKey $hn "requestGPUCores") -}}
{{- fail (printf "modelSpec '%s': gpuAllocation 'dra' cannot be combined with HAMi GPU requests in raySpec.headNode" .name) -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
  Name of the standalone ResourceClaimTemplate object for a model.
  Call with: include "chart.draClaimName" (dict "releaseName" .Release.Name "modelName" $modelSpec.name)
*/}}
{{- define "chart.draClaimName" -}}
{{- printf "%s-%s-dra-gpu" .releaseName .modelName -}}
{{- end -}}

{{/*
  Render the standalone ResourceClaimTemplate object (v1 GA schema).
  Inline pod-level resourceClaimTemplates is NOT used: the field is feature-gated
  and rejected by strict decoding on GA-enabled clusters (verified on k3s 1.36.4).
  Call with: include "chart.draClaimTemplate" (dict "releaseName" ... "namespace" ... "modelName" ... "deviceClass" ... "gpuCount" ...)
*/}}
{{- define "chart.draClaimTemplate" -}}
apiVersion: resource.k8s.io/v1
kind: ResourceClaimTemplate
metadata:
  name: {{ include "chart.draClaimName" . }}
  namespace: {{ .namespace }}
spec:
  spec:
    devices:
      requests:
        - name: gpu
          exactly:
            deviceClassName: {{ .deviceClass | default "gpu.nvidia.com" }}
            {{- if and (hasKey . "gpuCount") (ne (toString .gpuCount) "") }}
            {{- if gt (int .gpuCount) 1 }}
            count: {{ .gpuCount }}
            {{- end }}
            {{- end }}
{{- end -}}

{{/*
  Render the pod-level resourceClaims reference for DRA.
  Call with: include "chart.draPodClaims" (dict "releaseName" ... "modelName" ...)
*/}}
{{- define "chart.draPodClaims" -}}
resourceClaims:
  - name: gpu
    resourceClaimTemplateName: {{ include "chart.draClaimName" . }}
{{- end -}}

{{/*
  Merge ray head-node resource fields with the model's DRA settings so the
  head container can share chart.resources' DRA handling (claims emission).
  headNode.deviceClass / headNode.gpuCount override the model-level values.
  Call with: include "chart.rayHeadMerged" $modelSpec
*/}}
{{- define "chart.rayHeadMerged" -}}
{{- $head := default dict .raySpec.headNode -}}
{{- $merged := deepCopy $head -}}
{{- $_ := set $merged "gpuAllocation" (.gpuAllocation | default "device-plugin") -}}
{{- if eq (.gpuAllocation | default "device-plugin") "dra" -}}
{{- $_ := set $merged "deviceClass" (get $head "deviceClass" | default (.deviceClass | default "gpu.nvidia.com")) -}}
{{- $_ := set $merged "gpuCount" (get $head "gpuCount" | default 0) -}}
{{- end -}}
{{- toYaml $merged -}}
{{- end -}}

{{- define "chart.hasLimits" -}}
{{- $modelSpec := . -}}
{{- $gpuRequested := false -}}
{{- if and (hasKey $modelSpec "requestGPU") (ne (toString $modelSpec.requestGPU) "") -}}
{{- if gt (int $modelSpec.requestGPU) 0 -}}
{{- $gpuRequested = true -}}
{{- end -}}
{{- end -}}
{{- or
    (hasKey $modelSpec "limitMemory")
    (hasKey $modelSpec "limitCPU")
    $gpuRequested
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
{{- $dra := eq ($modelSpec.gpuAllocation | default "device-plugin") "dra" -}}
requests:
  memory: {{ required "Value 'modelSpec.requestMemory' must be defined !" ($modelSpec.requestMemory | quote) }}
  cpu: {{ required "Value 'modelSpec.requestCPU' must be defined !" ($modelSpec.requestCPU | quote) }}
  {{- if and (not $dra) (hasKey $modelSpec "requestGPU") (ne (toString $modelSpec.requestGPU) "") (gt (int $modelSpec.requestGPU) 0) }}
  {{- $gpuType := default "nvidia.com/gpu" $modelSpec.requestGPUType }}
  {{ $gpuType }}: {{ required "Value 'modelSpec.requestGPU' must be defined !" ($modelSpec.requestGPU | quote) }}
  {{- end }}
  {{- if and (not $dra) (hasKey $modelSpec "requestGPUMem") }}
  nvidia.com/gpumem: {{ $modelSpec.requestGPUMem | quote }}
  {{- end }}
  {{- if and (not $dra) (hasKey $modelSpec "requestGPUMemPercentage") }}
  nvidia.com/gpumem-percentage: {{ $modelSpec.requestGPUMemPercentage | quote }}
  {{- end }}
  {{- if and (not $dra) (hasKey $modelSpec "requestGPUCores") }}
  nvidia.com/gpucores: {{ $modelSpec.requestGPUCores | quote }}
  {{- end }}
{{- $hasDraClaim := false -}}
{{- if $dra -}}
  {{- $count := 1 -}}
  {{- if hasKey $modelSpec "gpuCount" -}}
    {{- $count = int $modelSpec.gpuCount -}}
  {{- end -}}
  {{- if gt $count 0 -}}
    {{- $hasDraClaim = true -}}
  {{- end -}}
{{- end -}}
{{- if $hasDraClaim }}
claims:
  - name: gpu
{{- end }}
{{- if and (not $dra) (eq (include "chart.hasLimits" $modelSpec) "true") }}
limits:
  {{- if (hasKey $modelSpec "limitMemory") }}
  memory: {{ $modelSpec.limitMemory | quote }}
  {{- end }}
  {{- if (hasKey $modelSpec "limitCPU") }}
  cpu: {{ $modelSpec.limitCPU | quote }}
  {{- end }}
  {{- if (and (hasKey $modelSpec "requestGPU") (ne (toString $modelSpec.requestGPU) "") (gt (int $modelSpec.requestGPU) 0)) }}
  {{- $gpuType := default "nvidia.com/gpu" $modelSpec.requestGPUType }}
  {{ $gpuType }}: {{ required "Value 'modelSpec.requestGPU' must be defined !" ($modelSpec.requestGPU | quote) }}
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
