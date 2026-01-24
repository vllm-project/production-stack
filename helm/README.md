# vLLM Production Stack helm chart

This helm chart lets users deploy multiple serving engines and a router into the Kubernetes cluster.

## Key features

- Support running multiple serving engines with multiple different models
- Load the model weights directly from the existing PersistentVolumes

## Prerequisites

1. A running Kubernetes cluster with GPU. (You can set it up through `minikube`: <https://minikube.sigs.k8s.io/docs/tutorials/nvidia/>)
2. [Helm](https://helm.sh/docs/intro/install/)

## Install the helm chart

```bash
helm install llmstack . -f values-example.yaml
```

## Uninstall the deployment

run `helm uninstall llmstack`

## Configure the deployments

See `helm/values.yaml` for mode details.

## Production Stack Helm Chart Values Reference

This table documents all available configuration values for the Production Stack Helm chart.

### Table of Contents

- [Serving Engine Configuration](#serving-engine-configuration)
- [Router Configuration](#router-configuration)
- [Cache Server Configuration](#cache-server-configuration)
- [LoRA Adapters Configuration](#lora-adapters-configuration)
- [LoRA Controller Configuration](#lora-controller-configuration)
- [Shared Storage Configuration](#shared-storage-configuration)

### Serving Engine Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `servingEngineSpec.enableEngine` | boolean | `true` | Whether to enable the serving engine deployment |
| `servingEngineSpec.labels` | map | `{environment: "test", release: "test"}` | Customized labels for the serving engine deployment |
| `servingEngineSpec.vllmApiKey` | string/map | `null` | (Optional) API key for securing vLLM models. Can be a direct string or an object referencing an existing secret |
| `servingEngineSpec.modelSpec` | list | `[]` | Array of specifications for configuring multiple serving engine deployments running different models |
| `servingEngineSpec.containerPort` | integer | `8000` | Port the vLLM server container is listening on |
| `servingEngineSpec.servicePort` | integer | `80` | Port the service will listen on |
| `servingEngineSpec.configs` | map | `{}` | Set other environment variables from a config map |
| `servingEngineSpec.strategy` | map | `{}` | Deployment strategy for the serving engine pods |
| `servingEngineSpec.maxUnavailablePodDisruptionBudget` | string | `""` | Configuration for the PodDisruptionBudget for the serving engine pods |
| `servingEngineSpec.tolerations` | list | `[]` | Tolerations configuration for the serving engine pods (when there are taints on nodes) |
| `servingEngineSpec.runtimeClassName` | string | `"nvidia"` | RuntimeClassName configuration (set to "nvidia" if using GPU) |
| `servingEngineSpec.schedulerName` | string | `""` | SchedulerName configuration for the serving engine pods |
| `servingEngineSpec.securityContext` | map | `{}` | Pod-level security context configuration for the serving engine pods |
| `servingEngineSpec.containerSecurityContext` | map | `{runAsNonRoot: false}` | Container-level security context configuration for the serving engine container |
| `servingEngineSpec.extraPorts` | list | `[]` | List of additional ports to expose for the serving engine container |
| `servingEngineSpec.startupProbe.initialDelaySeconds` | integer | `15` | Number of seconds after container starts before startup probe is initiated |
| `servingEngineSpec.startupProbe.periodSeconds` | integer | `10` | How often (in seconds) to perform the startup probe |
| `servingEngineSpec.startupProbe.failureThreshold` | integer | `60` | Number of failures before considering failed |
| `servingEngineSpec.startupProbe.httpGet.path` | string | `"/health"` | Path to access on the HTTP server |
| `servingEngineSpec.startupProbe.httpGet.port` | integer | `8000` | Port to access on the container |
| `servingEngineSpec.livenessProbe.initialDelaySeconds` | integer | `15` | Number of seconds after container starts before liveness probe is initiated |
| `servingEngineSpec.livenessProbe.periodSeconds` | integer | `10` | How often (in seconds) to perform the liveness probe |
| `servingEngineSpec.livenessProbe.failureThreshold` | integer | `3` | Number of failures before considering failed |
| `servingEngineSpec.livenessProbe.httpGet.path` | string | `"/health"` | Path to access on the HTTP server |
| `servingEngineSpec.livenessProbe.httpGet.port` | integer | `8000` | Port to access on the container |
| `servingEngineSpec.imagePullPolicy` |  string | `"Always"`| Image pull policy for serving engine |
| `servingEngineSpec.extraVolumes` | list | `[]`| Extra volumes for serving engine |
| `servingEngineSpec.extraVolumeMounts` | list | `[]` | Extra volume mounts for serving engine |

#### Model Specification Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `servingEngineSpec.modelSpec[].annotations` | map | `{}` | (Optional) Annotations to add to the deployment, e.g., {model: "opt125m"} |
| `servingEngineSpec.modelSpec[].podAnnotations` | map | `{}` | (Optional) Annotations to add to the pod, e.g., {model: "opt125m"} |
| `servingEngineSpec.modelSpec[].name` | string | `""` | The name of the model, e.g., "example-model" |
| `servingEngineSpec.modelSpec[].repository` | string | `""` | The repository of the model, e.g., "vllm/vllm-openai" |
| `servingEngineSpec.modelSpec[].tag` | string | `""` | The tag of the model, e.g., "latest" |
| `servingEngineSpec.modelSpec[].imagePullSecret` | string | `""` | (Optional) Name of secret with credentials to private container repository |
| `servingEngineSpec.modelSpec[].modelURL` | string | `""` | The URL of the model, e.g., "facebook/opt-125m" |
| `servingEngineSpec.modelSpec[].chatTemplate` | string | `null` | (Optional) Chat template (Jinja2) specifying tokenizer configuration |
| `servingEngineSpec.modelSpec[].replicaCount` | integer | `1` | The number of replicas for the model |
| `servingEngineSpec.modelSpec[].requestCPU` | integer | `0` | The number of CPUs requested for the model |
| `servingEngineSpec.modelSpec[].requestMemory` | string | `""` | The amount of memory requested for the model, e.g., "16Gi" |
| `servingEngineSpec.modelSpec[].requestGPU` | integer | `0` | The number of GPUs requested for the model |
| `servingEngineSpec.modelSpec[].requestGPUType` | string | `"nvidia.com/gpu"` | (Optional) The type of GPU requested, e.g., "nvidia.com/mig-4g.71gb" |
| `servingEngineSpec.modelSpec[].limitCPU` | string | `""` | (Optional) The CPU limit for the model, e.g., "8" |
| `servingEngineSpec.modelSpec[].limitMemory` | string | `""` | (Optional) The memory limit for the model, e.g., "32Gi" |
| `servingEngineSpec.modelSpec[].shmSize` | string | `"20Gi"` | Size of the shared memory for the serving engine container (applied when tensor parallelism is enabled) |
| `servingEngineSpec.modelSpec[].enableLoRA` | boolean | `true` | (Optional) Whether to enable LoRA |
| `servingEngineSpec.modelSpec[].pvcStorage` | string | `""` | (Optional) The amount of storage requested for the model, e.g., "50Gi" |
| `servingEngineSpec.modelSpec[].pvcAccessMode` | list | `[]` | (Optional) The access mode policy for the mounted volume, e.g., ["ReadWriteOnce"] |
| `servingEngineSpec.modelSpec[].storageClass` | string | `""` | (Optional) The storage class of the PVC |
| `servingEngineSpec.modelSpec[].pvcMatchLabels` | map | `{}` | (Optional) The labels to match the PVC, e.g., {model: "opt125m"} |
| `servingEngineSpec.modelSpec[].pvcLabels` | map | `{}` | (Optional) The labels to add to the PVC, e.g., {label_excluded_from_alerts: "true"} |
| `servingEngineSpec.modelSpec[].extraVolumes` | list | `[]` | (Optional) Additional volumes to add to the pod, in Kubernetes volume format |
| `servingEngineSpec.modelSpec[].extraVolumeMounts` | list | `[]` | (Optional) Additional volume mounts to add to the container, in Kubernetes volumeMount format |
| `servingEngineSpec.modelSpec[].serviceAccountName` | string | `""` | (Optional) The name of the service account to use for the deployment |
| `servingEngineSpec.modelSpec[].priorityClassName` | string | `""` | Priority class name for the deployment |
| `servingEngineSpec.modelSpec[].hf_token` | string/map | - | (Optional) Hugging Face token configuration |
| `servingEngineSpec.modelSpec[].env` | list | - | (Optional) Environment variables for the container |
| `servingEngineSpec.modelSpec[].nodeName` | string | - | (Optional) Direct node assignment |
| `servingEngineSpec.modelSpec[].nodeSelectorTerms` | list | - | (Optional) Node selector terms |

#### Init Container Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `servingEngineSpec.modelSpec[].initContainer.name` | string | `""` | The name of the init container, e.g., "init" |
| `servingEngineSpec.modelSpec[].initContainer.image` | string | `""` | The Docker image for the init container, e.g., "busybox:latest" |
| `servingEngineSpec.modelSpec[].initContainer.command` | list | `[]` | (Optional) The command to run in the init container, e.g., ["sh", "-c"] |
| `servingEngineSpec.modelSpec[].initContainer.args` | list | `[]` | (Optional) Additional arguments to pass to the command, e.g., ["ls"] |
| `servingEngineSpec.modelSpec[].initContainer.env` | list | `[]` | (Optional) List of environment variables to set in the container |
| `servingEngineSpec.modelSpec[].initContainer.resources` | map | `{}` | (Optional) The resource requests and limits for the container |
| `servingEngineSpec.modelSpec[].initContainer.mountPvcStorage` | boolean | `false` | (Optional) Whether to mount the model's volume |

#### vLLM Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `servingEngineSpec.modelSpec[].vllmConfig.v0` | integer | - | Specify to 1 to use vLLM v0, otherwise vLLM v1 |
| `servingEngineSpec.modelSpec[].vllmConfig.enablePrefixCaching` | boolean | `false` | Enable prefix caching |
| `servingEngineSpec.modelSpec[].vllmConfig.enableChunkedPrefill` | boolean | `false` | Enable chunked prefill |
| `servingEngineSpec.modelSpec[].vllmConfig.maxModelLen` | integer | `4096` | The maximum model length, e.g., 16384 |
| `servingEngineSpec.modelSpec[].vllmConfig.dtype` | string | `"fp16"` | The data type, e.g., "bfloat16" |
| `servingEngineSpec.modelSpec[].vllmConfig.tensorParallelSize` | integer | `1` | The degree of tensor parallelism, e.g., 2 |
| `servingEngineSpec.modelSpec[].vllmConfig.maxNumSeqs` | integer | `256` | Maximum number of sequences to be processed in a single iteration |
| `servingEngineSpec.modelSpec[].vllmConfig.maxLoras` | integer | `0` | The maximum number of LoRA models to be loaded in a single batch |
| `servingEngineSpec.modelSpec[].vllmConfig.gpuMemoryUtilization` | number | `0.9` | The fraction of GPU memory to be used for the model executor (0-1) |
| `servingEngineSpec.modelSpec[].vllmConfig.extraArgs` | list | `["--disable-log-requests"]` | Extra command line arguments to pass to vLLM |

#### LMCache Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `servingEngineSpec.modelSpec[].lmcacheConfig.enabled` | boolean | `false` | Enable LMCache |
| `servingEngineSpec.modelSpec[].lmcacheConfig.cpuOffloadingBufferSize` | string | `"4"` | The CPU offloading buffer size, e.g., "30" |
| `servingEngineSpec.modelSpec[].lmcacheConfig.diskOffloadingBufferSize` | string | `""` | The disk offloading buffer size, e.g., "10Gi" |
| `servingEngineSpec.modelSpec[].lmcacheConfig.enableController` | boolean | `true` | Enable LMCache controller for KV-aware routing |
| `servingEngineSpec.modelSpec[].lmcacheConfig.instanceId` | string | `"default1"` | Unique instance identifier for controller |
| `servingEngineSpec.modelSpec[].lmcacheConfig.controllerPort` | string | `"9000"` | Controller port for KV coordination |
| `servingEngineSpec.modelSpec[].lmcacheConfig.workerPort` | integer | `8001` | Worker port for cache communication |
| `servingEngineSpec.modelSpec[].lmcacheConfig.kvRole` | string | - | KV cache role (for disaggregated prefill) - "kv_producer" or "kv_consumer" |
| `servingEngineSpec.modelSpec[].lmcacheConfig.enableNixl` | boolean | `true` | Enable NIXL protocol for KV transfer |
| `servingEngineSpec.modelSpec[].lmcacheConfig.nixlRole` | string | - | NIXL role for distributed caching - "sender" or "receiver" |
| `servingEngineSpec.modelSpec[].lmcacheConfig.nixlPeerHost` | string | `"decode-service"` | NIXL peer host for KV transfer |
| `servingEngineSpec.modelSpec[].lmcacheConfig.nixlPeerPort` | string | `"55555"` | NIXL peer port for KV transfer |
| `servingEngineSpec.modelSpec[].lmcacheConfig.nixlBufferSize` | string | `"1073741824"` | NIXL buffer size for KV transfer |

### Router Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `routerSpec.repository` | string | `"lmcache/lmstack-router"` | Docker image repository for the router |
| `routerSpec.tag` | string | `"latest"` | Docker image tag for the router |
| `routerSpec.imagePullPolicy` | string | `"Always"` | Image pull policy for the router |
| `routerSpec.imagePullSecrets` | list | `[]` | Image pull secrets for private container registries |
| `routerSpec.enableRouter` | boolean | `true` | Whether to enable the router service |
| `routerSpec.replicaCount` | integer | `1` | Number of replicas for the router pod |
| `routerSpec.priorityClassName` | string | `""` | Priority class for router |
| `routerSpec.containerPort` | integer | `8000` | Port the router container is listening on |
| `routerSpec.serviceType` | string | `"ClusterIP"` | Kubernetes service type for the router |
| `routerSpec.serviceAnnotations` | map | `{}` | Service annotations for LoadBalancer/NodePort |
| `routerSpec.servicePort` | integer | `80` | Port the router service will listen on |
| `routerSpec.serviceDiscovery` | string | `"k8s"` | Service discovery mode ("k8s" or "static") |
| `routerSpec.k8sServiceDiscoveryType` | string | `"pod-ip"` | Service discovery Type ("pod-ip" or "service-name") if serviceDiscovery is "k8s" |
| `routerSpec.staticBackends` | string | `""` | Comma-separated list of backend addresses if serviceDiscovery is "static" |
| `routerSpec.staticModels` | string | `""` | Comma-separated list of model names if serviceDiscovery is "static" |
| `routerSpec.routingLogic` | string | `"roundrobin"` | Routing logic ("roundrobin" or "session") |
| `routerSpec.sessionKey` | string | `""` | Session key if using "session" routing logic |
| `routerSpec.extraArgs` | list | `[]` | Extra command line arguments to pass to the router |
| `routerSpec.engineScrapeInterval` | integer | `15` | Interval in seconds to scrape metrics from the serving engine |
| `routerSpec.requestStatsWindow` | integer | `60` | Window size in seconds for calculating request statistics |
| `routerSpec.strategy` | map | `{}` | Deployment strategy for the router pods |
| `routerSpec.vllmApiKey` | string/map | `null` | (Optional) API key for securing vLLM models |
| `routerSpec.resources.requests.cpu` | string | `"4"` | CPU requests for router |
| `routerSpec.resources.requests.memory` | string | `"16G"` | Memory requests for router |
| `routerSpec.resources.limits.cpu` | string | `"8"` | CPU limits for router |
| `routerSpec.resources.limits.memory` | string | `"32G"` | Memory limits for router |
| `routerSpec.labels` | map | `{environment: "router", release: "router"}` | Customized labels for the router deployment |
| `routerSpec.podAnnotations` | map | `{}` | (Optional) Annotations to add to the pod, e.g., {model: "opt125m"} |
| `routerSpec.affinity` | map | {} | (Optional) Affinity configuration. If specified, this takes precedence over `nodeSelectorTerms`. |
| `routerSpec.nodeSelectorTerms` | list | `[]` | (Optional) Node selector terms. This is ignored if `affinity` is specified. |
| `routerSpec.hf_token` | string | `""`| Hugging Face token for router |
| `routerSpec.lmcacheControllerPort` | string |`"8000"`|LMCache controller port |
| `routerSpec.livenessProbe.initialDelaySeconds` | integer |`30`| Initial delay in seconds for router's liveness probe |
| `routerSpec.livenessProbe.periodSeconds` | integer |`5`| Interval in seconds for router's liveness probe |
| `routerSpec.livenessProbe.failureThreshold` | integer |`3`| Failure threshold for router's liveness probe |
| `routerSpec.livenessProbe.httpGet.path` | string |`"/health"`| Endpoint that the router's liveness probe will be testing |
| `routerSpec.startupProbe.initialDelaySeconds` | integer |`5`| Initial delay in seconds for router's startup probe |
| `routerSpec.startupProbe.periodSeconds` | integer |`5`| Interval in seconds for router's startup probe |
| `routerSpec.startupProbe.failureThreshold` | integer |`3`| Failure threshold for router's startup probe |
| `routerSpec.startupProbe.httpGet.path` | string |`"/health"`| Endpoint that the router's startup probe will be testing |
| `routerSpec.readinessProbe.initialDelaySeconds` | integer |`30`| Initial delay in seconds for router's readiness probe |
| `routerSpec.readinessProbe.periodSeconds` | integer |`5`| Interval in seconds for router's readiness probe |
| `routerSpec.readinessProbe.failureThreshold` | integer |`3`| Failure threshold for router's readiness probe |
| `routerSpec.readinessProbe.httpGet.path` | string |`"/health"`| Endpoint that the router's readiness probe will be testing |

#### Router OpenTelemetry Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `routerSpec.otel.endpoint` | string | `""` | OTLP endpoint for tracing (e.g., "otel-collector:4317"). Tracing is enabled when this is set. |
| `routerSpec.otel.serviceName` | string | `"vllm-router"` | Service name for OpenTelemetry traces |
| `routerSpec.otel.secure` | boolean | `false` | Use secure (TLS) connection for OTLP exporter |

#### Router Ingress Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `routerSpec.ingress.enabled` | boolean | `false` | Enable Ingress controller resource for the router |
| `routerSpec.ingress.className` | string | `""` | IngressClass to use for the router Ingress resource |
| `routerSpec.ingress.annotations` | map | `{}` | Additional annotations for the router Ingress resource |
| `routerSpec.ingress.hosts` | list | `[{host: "vllm-router.local", paths: [{path: /, pathType: Prefix}]}]` | List of hostnames covered by the router Ingress record |
| `routerSpec.ingress.tls` | list | `[]` | TLS configuration for hostnames covered by the router Ingress record |

### Cache Server Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `cacheserverSpec.enableServer` | boolean | `false` | Whether to enable the cache server deployment |
| `cacheserverSpec.image.repository` | string | `"lmcache/lmstack-cache-server"` | Docker image repository for the cache server |
| `cacheserverSpec.image.tag` | string | `"latest"` | Docker image tag for the cache server |
| `cacheserverSpec.image.pullPolicy` | string | `"Always"` | Image pull policy for the cache server |
| `cacheserverSpec.imagePullSecrets` | list | `[]` | Image pull secrets for private container registries |
| `cacheserverSpec.replicaCount` | integer | `1` | Number of replicas for the cache server pod |
| `cacheserverSpec.containerPort` | integer | `8000` | Port the cache server container is listening on |
| `cacheserverSpec.serviceType` | string | `"ClusterIP"` | Kubernetes service type for the cache server |
| `cacheserverSpec.servicePort` | integer | `80` | Port the cache server service will listen on |
| `cacheserverSpec.resources.requests.cpu` | string | `"1"` | CPU requests for cache server |
| `cacheserverSpec.resources.requests.memory` | string | `"2G"` | Memory requests for cache server |
| `cacheserverSpec.resources.limits.cpu` | string | `"2"` | CPU limits for cache server |
| `cacheserverSpec.resources.limits.memory` | string | `"4G"` | Memory limits for cache server |
| `cacheserverSpec.labels` | map | `{environment: "cache", release: "cache"}` | Customized labels for the cache server deployment |
| `cacheserverSpec.strategy` | map | `{}` | Deployment strategy for the cache server pods |
| `cacheserverSpec.startupProbe` | map | `{initialDelaySeconds: 15, periodSeconds: 10, failureThreshold: 60, httpGet: {path: /health, port: 8000}}` | Configuration for the startup probe |
| `cacheserverSpec.livenessProbe` | map | `{initialDelaySeconds: 15, periodSeconds: 10, failureThreshold: 3, httpGet: {path: /health, port: 8000}}` | Configuration for the liveness probe |
| `cacheserverSpec.maxUnavailablePodDisruptionBudget` | string | `""` | Configuration for the PodDisruptionBudget |
| `cacheserverSpec.tolerations` | list | `[]` | Tolerations configuration for the cache server pods |
| `cacheserverSpec.runtimeClassName` | string | `""` | RuntimeClassName configuration for the cache server pods |
| `cacheserverSpec.schedulerName` | string | `""` | SchedulerName configuration for the cache server pods |
| `cacheserverSpec.securityContext` | map | `{}` | Pod-level security context configuration |
| `cacheserverSpec.containerSecurityContext` | map | `{runAsNonRoot: false}` | Container-level security context configuration |
| `cacheserverSpec.priorityClassName` | string | - | Priority class for cache server |
| `cacheserverSpec.affinity` | map | - | (Optional) Affinity configuration. If specified, this takes precedence over `nodeSelectorTerms`. |
| `cacheserverSpec.nodeSelectorTerms` | list | - | (Optional) Node selector terms. This is ignored if `affinity` is specified. |
| `cacheserverSpec.serde` | string | - | Serialization/deserialization format |

### LoRA Adapters Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `loraAdapters` | list | `[]` | Array of LoRA adapter instances to deploy |
| `loraAdapters[].name` | string | - | Name of the LoRA adapter instance |
| `loraAdapters[].baseModel` | string | - | Name of the base model this adapter is for |
| `loraAdapters[].vllmApiKey.secretRef.secretName` | string | - | Name of the secret containing API key |
| `loraAdapters[].vllmApiKey.secretRef.secretKey` | string | - | Key in the secret containing API key |
| `loraAdapters[].vllmApiKey.value` | string | - | Direct API key value |
| `loraAdapters[].adapterSource.type` | string | - | Type of adapter source (local, s3, http, huggingface) |
| `loraAdapters[].adapterSource.adapterName` | string | - | Name of the adapter to apply |
| `loraAdapters[].adapterSource.adapterPath` | string | - | Path to the LoRA adapter weights |
| `loraAdapters[].adapterSource.repository` | string | - | Repository to get the LoRA adapter from |
| `loraAdapters[].adapterSource.pattern` | string | - | Pattern to use for the adapter name |
| `loraAdapters[].adapterSource.maxAdapters` | integer | - | Maximum number of adapters to load |
| `loraAdapters[].adapterSource.credentials.secretName` | string | - | Name of secret with storage credentials |
| `loraAdapters[].adapterSource.credentials.secretKey` | string | - | Key in secret containing credentials |
| `loraAdapters[].loraAdapterDeploymentConfig.algorithm` | string | - | Placement algorithm (default, ordered, equalized) |
| `loraAdapters[].loraAdapterDeploymentConfig.replicas` | integer | - | Number of replicas that should load this adapter |
| `loraAdapters[].labels` | map | - | Additional labels for the LoRA adapter |

### LoRA Controller Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `loraController.enableLoraController` | boolean | `false` | Whether to enable the LoRA controller |
| `loraController.kubernetesClusterDomain` | string | `"cluster.local"` | Kubernetes cluster domain |
| `loraController.replicaCount` | integer | `1` | Number of LoRA controller replicas |
| `loraController.image.repository` | string | `"lmcache/lmstack-lora-controller"` | Docker image repository |
| `loraController.image.tag` | string | `"latest"` | Docker image tag |
| `loraController.image.pullPolicy` | string | `"IfNotPresent"` | Image pull policy |
| `loraController.imagePullSecrets` | list | `[]` | Image pull secrets |
| `loraController.podAnnotations` | map | `{}` | Pod annotations |
| `loraController.podSecurityContext.runAsNonRoot` | boolean | `true` | Run as non-root user |
| `loraController.podSecurityContext.seccompProfile.type` | string | `RuntimeDefault` | Seccomp profile type |
| `loraController.containerSecurityContext.allowPrivilegeEscalation` | boolean | `false` | Allow privilege escalation |
| `loraController.containerSecurityContext.capabilities.drop` | list | `["ALL"]` | Drop capabilities |
| `loraController.resources` | map | `{}` | Resource requests and limits |
| `loraController.nodeSelector` | map | `{}` | Node selector |
| `loraController.affinity` | map | `{}` | Affinity configuration |
| `loraController.tolerations` | list | `[]` | Tolerations configuration |
| `loraController.env` | list | `[]` | Environment variables |
| `loraController.extraArgs` | list | `[]` | Extra arguments for the controller |

### Shared Storage Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `sharedStorage.enabled` | boolean | `false` | Whether to enable shared storage for the models |
| `sharedStorage.size` | string | `"100Gi"` | Size of the shared storage volume |
| `sharedStorage.accessModes` | list | `["ReadWriteOnce"]` | Access modes for the shared storage volume |
| `sharedStorage.storageClass` | string | `"standard"` | Storage class name for the shared storage volume |
| `sharedStorage.hostPath` | string | `""` | Host path for the shared storage volume (for local testing only) |
| `sharedStorage.nfs.server` | string | `""` | NFS server address for the shared storage volume |
| `sharedStorage.nfs.path` | string | `""` | NFS export path for the shared storage volume |
