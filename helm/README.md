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

## VLLM Production-stack helm chart configuration

| Key                                | Description                                                                                                                               | Type     | Default                 |
| :--------------------------------- | :---------------------------------------------------------------------------------------------------------------------------------------- | :------- | :---------------------- |
| `servingEngineSpec.enableEngine`   | Whether to enable the serving engine deployment.                                                                                          | boolean  | `true`                  |
| `servingEngineSpec.labels`         | Customized labels for the serving engine deployment.                                                                                       | map      | `{environment: "test", release: "test"}` |
| `servingEngineSpec.vllmApiKey`       | (Optional) API key for securing the vLLM models. Can be a direct string or an object referencing an existing secret.                       | string/map | `null`                  |
| `servingEngineSpec.containerPort` | Port the vLLM server container is listening on.                                                                                          | integer  | `8000`                  |
| `servingEngineSpec.servicePort`   | Port the service will listen on.                                                                                                          | integer  | `80`                    |
| `servingEngineSpec.configs`       | Set other environment variables from a config map.                                                                                        | map      | `{}`                    |
| `servingEngineSpec.strategy`      | Deployment strategy for the serving engine pods.                                                                                         | map      | `{}`                    |
| `servingEngineSpec.startupProbe`  | Configuration for the startup probe of the serving engine container.                                                                     | map      | `{initialDelaySeconds: 15, periodSeconds: 10, failureThreshold: 60, httpGet: {path: /health, port: 8000}}` |
| `servingEngineSpec.livenessProbe` | Configuration for the liveness probe of the serving engine container.                                                                      | map      | `{initialDelaySeconds: 15, periodSeconds: 10, failureThreshold: 3, httpGet: {path: /health, port: 8000}}` |
| `servingEngineSpec.maxUnavailablePodDisruptionBudget` | Configuration for the PodDisruptionBudget for the serving engine pods.                                                              | string   | `""`                    |
| `servingEngineSpec.tolerations`   | Tolerations configuration for the serving engine pods (when there are taints on nodes).                                                      | list     | `[]`                    |
| `servingEngineSpec.runtimeClassName` | RuntimeClassName configuration for the serving engine pods (set to "nvidia" if using GPU).                                                   | string   | `"nvidia"`              |
| `servingEngineSpec.schedulerName` | SchedulerName configuration for the serving engine pods.                                                                                 | string   | `""`                    |
| `servingEngineSpec.securityContext` | Pod-level security context configuration for the serving engine pods.                                                                      | map      | `{}`                    |
| `servingEngineSpec.containerSecurityContext` | Container-level security context configuration for the serving engine container.                                                      | map      | `{runAsNonRoot: false}` |
| `servingEngineSpec.extraPorts`   | List of additional ports to expose for the serving engine container.                                                                   | list     | `[]`                    |
| `servingEngineSpec.modelSpec`      | Array of specifications for configuring multiple serving engine deployments running different models.                                     | list     | `[]`                    |
| `servingEngineSpec.modelSpec[].annotations` | (Optional, map) The annotations to add to the deployment, e.g., {model: "opt125m"}.                                                   | map      | `{}`                    |
| `servingEngineSpec.modelSpec[].serviceAccountName` | (Optional, string) The name of the service account to use for the deployment, e.g., "vllm-service-account".                 | string   | `""`                    |
| `servingEngineSpec.modelSpec[].podAnnotations` | (Optional, map) The annotations to add to the pod, e.g., {model: "opt125m"}.                                                   | map      | `{}`                    |
| `servingEngineSpec.modelSpec[].name`       | (string) The name of the model, e.g., "example-model".                                                                                  | string   | `""`                    |
| `servingEngineSpec.modelSpec[].repository` | (string) The repository of the model, e.g., "vllm/vllm-openai".                                                                        | string   | `""`                    |
| `servingEngineSpec.modelSpec[].tag`        | (string) The tag of the model, e.g., "latest".                                                                                          | string   | `""`                    |
| `servingEngineSpec.modelSpec[].imagePullSecret` | (Optional, string) Name of secret with credentials to private container repository, e.g. "secret".                                | string   | `""`                    |
| `servingEngineSpec.modelSpec[].modelURL`     | (string) The URL of the model, e.g., "facebook/opt-125m".                                                                            | string   | `""`                    |
| `servingEngineSpec.modelSpec[].chatTemplate` | (Optional, string) Chat template (Jinga2) specifying tokenizer configuration, e.g. "`{% for message in messages %}\n{% if message['role'] == 'user' %}\n{{ 'Question:\n' + message['content'] + '\n\n' }}{% elif message['role'] == 'system' %}\n{{ 'System:\n' + message['content'] + '\n\n' }}{% elif message['role'] == 'assistant' %}{{ 'Answer:\n'  + message['content'] + '\n\n' }}{% endif %}\n{% if loop.last and add_generation_prompt %}\n{{ 'Answer:\n' }}{% endif %}{% endfor %}`" | string   | `null`                  |
| `servingEngineSpec.modelSpec[].replicaCount` | (int) The number of replicas for the model, e.g. 1                                                                                     | integer  | `1`                     |
| `servingEngineSpec.modelSpec[].requestCPU`   | (int) The number of CPUs requested for the model, e.g. 6                                                                                | integer  | `0`                     |
| `servingEngineSpec.modelSpec[].requestMemory` | (string) The amount of memory requested for the model, e.g., "16Gi".                                                                  | string   | `""`                    |
| `servingEngineSpec.modelSpec[].requestGPU`   | (int) The number of GPUs requested for the model, e.g., 1                                                                                | integer  | `0`                     |
| `servingEngineSpec.modelSpec[].requestGPUType` | (Optional, string) The type of GPU requested, e.g., "nvidia.com/mig-4g.71gb". If not specified, defaults to "nvidia.com/gpu"         | string   | `"nvidia.com/gpu"`      |
| `servingEngineSpec.modelSpec[].limitCPU`     | (Optional, string) The CPU limit for the model, e.g., "8".                                                                          | string   | `""`                    |
| `servingEngineSpec.modelSpec[].limitMemory`  | (Optional, string) The memory limit for the model, e.g., "32Gi".                                                                      | string   | `""`                    |
| `servingEngineSpec.modelSpec[].shmSize`       | Size of the shared memory for the serving engine container. It is only applied when tensor parallelism is enabled.                                                                               | string   | `"20Gi"`                |
| `servingEngineSpec.modelSpec[].enableLoRA`  | (Optional, boolean) Whether to enable LoRA | boolean | `true`|
| `servingEngineSpec.modelSpec[].pvcStorage`   | (Optional, string) The amount of storage requested for the model, e.g., "50Gi".                                                      | string   | `""`                    |
| `servingEngineSpec.modelSpec[].pvcAccessMode` | (Optional, list) The access mode policy for the mounted volume, e.g., ["ReadWriteOnce"]                                              | list     | `[]`                    |
| `servingEngineSpec.modelSpec[].storageClass` | (Optional, String) The storage class of the PVC e.g., "", default is ""                                                               | string   | `""`                    |
| `servingEngineSpec.modelSpec[].pvcMatchLabels` | (Optional, map) The labels to match the PVC, e.g., {model: "opt125m"}.                                                            | map      | `{}`                    |
| `servingEngineSpec.modelSpec[].extraVolumes` | (Optional, list) Additional volumes to add to the pod, in Kubernetes volume format. [reference](https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.32/#volume-v1-core) | list     | `[]`                    |
| `servingEngineSpec.modelSpec[].extraVolumeMounts` | (Optional, list) Additional volume mounts to add to the container, in Kubernetes volumeMount format. [reference](https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.32/#volumemount-v1-core) | list     | `[]`                    |
| `servingEngineSpec.modelSpec[].initContainer` | (optional, list of objects) The configuration for the init container to be run before the main container.                          | list     | `[]`                    |
| `servingEngineSpec.modelSpec[].initContainer.name` | (string) The name of the init container, e.g., "init"                                                                              | string   | `""`                    |
| `servingEngineSpec.modelSpec[].initContainer.image` | (string) The Docker image for the init container, e.g., "busybox:latest"                                                         | string   | `""`                    |
| `servingEngineSpec.modelSpec[].initContainer.command` | (optional, list) The command to run in the init container, e.g., ["sh", "-c"]                                                      | list     | `[]`                    |
| `servingEngineSpec.modelSpec[].initContainer.args` | (optional, list) Additional arguments to pass to the command, e.g., ["ls"]                                                          | list     | `[]`                    |
| `servingEngineSpec.modelSpec[].initContainer.env` | (optional, list) List of environment variables to set in the container, each being a map with:                                     | list     | `[]`                    |
| `servingEngineSpec.modelSpec[].initContainer.resources` | (optional, map) The resource requests and limits for the container:                                                              | map      | `{}`                    |
| `servingEngineSpec.modelSpec[].initContainer.mountPvcStorage` | (optional, bool) Whether to mount the model's volume.                                                                    | boolean  | `false`                 |
| `servingEngineSpec.modelSpec[].vllmConfig` | (optional, map) The configuration for the VLLM model, supported options are:                                                         | map      | `{}`                    |
| `servingEngineSpec.modelSpec[].vllmConfig.enablePrefixCaching` | (optional, bool) Enable prefix caching, e.g., false                                                                    | boolean  | `false`                 |
| `servingEngineSpec.modelSpec[].vllmConfig.enableChunkedPrefill` | (optional, bool) Enable chunked prefill, e.g., false                                                                    | boolean  | `false`                 |
| `servingEngineSpec.modelSpec[].vllmConfig.maxModelLen` | (optional, int) The maximum model length, e.g., 16384                                                                            | integer  | `4096`                  |
| `servingEngineSpec.modelSpec[].vllmConfig.dtype` | (optional, string) The data type, e.g., "bfloat16"                                                                          | string   | `"fp16"`                |
| `servingEngineSpec.modelSpec[].vllmConfig.tensorParallelSize` | (optional, int) The degree of tensor parallelism, e.g., 2                                                             | integer  | `1`                     |
| `servingEngineSpec.modelSpec[].vllmConfig.maxNumSeqs` | (optional, int) Maximum number of sequences to be processed in a single iteration., e.g., 32                                     | integer  | `256`                   |
| `servingEngineSpec.modelSpec[].vllmConfig.maxLoras` | (optional, int) The maximum number of LoRA models to be loaded in a single batch, e.g., 4                                           | integer  | `0`                     |
| `servingEngineSpec.modelSpec[].vllmConfig.gpuMemoryUtilization` | (optional, float) The fraction of GPU memory to be used for the model executor, which can range from 0 to 1. e.g., 0.95 | number   | `0.9`                   |
| `servingEngineSpec.modelSpec[].vllmConfig.extraArgs` | (optional, list) Extra command line arguments to pass to vLLM, e.g., ["--disable-log-requests"]                                | list     | `[]`                    |
| `servingEngineSpec.modelSpec[].lmcacheConfig.enabled` | (optional, bool) Enable LMCache, e.g., true                                                                               | boolean  | `false`                 |
| `servingEngineSpec.modelSpec[].lmcacheConfig.cpuOffloadingBufferSize` | (optional, string) The CPU offloading buffer size, e.g., "30"                                                             | string   | `"4"`                   |
| `servingEngineSpec.modelSpec[].lmcacheConfig.diskOffloadingBufferSize` | (optional, string) The disk offloading buffer size, e.g., "10Gi"                                                            | string   | `""`                    |
| `servingEngineSpec.modelSpec[].lmcacheConfig.enableController` | (optional, bool) Enable LMCache controller for KV-aware routing.                                                         | boolean  | `true`                  |
| `servingEngineSpec.modelSpec[].lmcacheConfig.instanceId` | (optional, string) Unique instance identifier for controller.                                                                | string   | `"default1"`            |
| `servingEngineSpec.modelSpec[].lmcacheConfig.controllerPort` | (optional, string) Controller port for KV coordination.                                                                    | string   | `"9000"`                |
| `servingEngineSpec.modelSpec[].lmcacheConfig.workerPort` | (optional, integer) Worker port for cache communication.                                                                    | integer  | `8001`                  |
| `servingEngineSpec.modelSpec[].lmcacheConfig.kvRole` | (optional, string) KV cache role (for disaggregated prefill).                                                                  | string   | `"kv_producer"` or `"kv_consumer"` |
| `servingEngineSpec.modelSpec[].lmcacheConfig.enableNixl` | (optional, bool) Enable NIXL protocol for KV transfer.                                                                   | boolean  | `true`                  |
| `servingEngineSpec.modelSpec[].lmcacheConfig.nixlRole` | (optional, string) NIXL role for distributed caching.                                                                      | string   | `"sender"` or `"receiver"` |
| `servingEngineSpec.modelSpec[].lmcacheConfig.nixlPeerHost` | (optional, string) NIXL peer host for KV transfer.                                                                           | string   | `"decode-service"`      |
| `servingEngineSpec.modelSpec[].lmcacheConfig.nixlPeerPort` | (optional, string) NIXL peer port for KV transfer.                                                                         | string   | `"55555"`               |
| `servingEngineSpec.modelSpec[].lmcacheConfig.nixlBufferSize` | (optional, string) NIXL buffer size for KV transfer.                                                                       | string   | `"1073741824"`          |
| `routerSpec.repository`           | Docker image repository for the router.                                                                                                   | string   | `"lmcache/lmstack-router"` |
| `routerSpec.tag`                  | Docker image tag for the router.                                                                                                          | string   | `"latest"`              |
| `routerSpec.imagePullPolicy`      | Image pull policy for the router.                                                                                                         | string   | `"Always"`              |
| `routerSpec.enableRouter`         | Whether to enable the router service.                                                                                                    | boolean  | `true`                  |
| `routerSpec.replicaCount`         | Number of replicas for the router pod.                                                                                                   | integer  | `1`                     |
| `routerSpec.containerPort`        | Port the router container is listening on.                                                                                                | integer  | `8000`                  |
| `routerSpec.serviceType`          | Kubernetes service type for the router.                                                                                                   | string   | `"ClusterIP"`           |
| `routerSpec.servicePort`          | Port the router service will listen on.                                                                                                   | integer  | `80`                    |
| `routerSpec.serviceDiscovery`     | Service discovery mode for the router ("k8s" or "static").                                                                                 | string   | `"k8s"`                 |
| `routerSpec.staticBackends`       | Comma-separated list of backend addresses if serviceDiscovery is "static".                                                                | string   | `""`                    |
| `routerSpec.staticModels`         | Comma-separated list of model names if serviceDiscovery is "static".                                                                      | string   | `""`                    |
| `routerSpec.routingLogic`         | Routing logic for the router ("roundrobin" or "session").                                                                                | string   | `"roundrobin"`          |
| `routerSpec.sessionKey`           | Session key if using "session" routing logic.                                                                                             | string   | `""`                    |
| `routerSpec.extraArgs`            | Extra command line arguments to pass to the router.                                                                                     | list     | `[]`                    |
| `routerSpec.engineScrapeInterval` | Interval in seconds to scrape metrics from the serving engine.                                                                            | integer  | `15`                    |
| `routerSpec.requestStatsWindow`   | Window size in seconds for calculating request statistics.                                                                              | integer  | `60`                    |
| `routerSpec.strategy`             | Deployment strategy for the router pods.                                                                                                 | map      | `{}`                    |
| `routerSpec.vllmApiKey`           | (Optional) API key for securing the vLLM models. Can be a direct string or an object referencing an existing secret.                       | string/map | `null`                  |
| `routerSpec.resources`            | Resource requests and limits for the router container.                                                                                   | map      | `{requests: {cpu: "4", memory: "16G"}, limits: {cpu: "8", memory: "32G"}}` |
| `routerSpec.labels`               | Customized labels for the router deployment.                                                                                            | map      | `{environment: "router", release: "router"}` |
| `routerSpec.ingress.enabled`      | Enable Ingress controller resource for the router.                                                                                       | boolean  | `false`                 |
| `routerSpec.ingress.className`    | IngressClass to use for the router Ingress resource.                                                                                     | string   | `""`                    |
| `routerSpec.ingress.annotations`  | Additional annotations for the router Ingress resource.                                                                                 | map      | `{}`                    |
| `routerSpec.ingress.hosts`        | List of hostnames covered by the router Ingress record.                                                                                 | list     | `[{host: "vllm-router.local", paths: [{path: /, pathType: Prefix}]}]` |
| `routerSpec.ingress.tls`          | TLS configuration for hostnames covered by the router Ingress record.                                                                    | list     | `[]`                    |
| `routerSpec.nodeSelectorTerms`    | Node selector terms to match the nodes for the router pods.                                                                              | list     | `[]`        |
| `cacheServerSpec.enableServer`   | Whether to enable the cache server deployment.                                                                                         | boolean  | `false`                 |
| `cacheServerSpec.image.repository` | Docker image repository for the cache server.                                                                                          | string   | `"lmcache/lmstack-cache-server"` |
| `cacheServerSpec.image.tag`      | Docker image tag for the cache server.                                                                                                 | string   | `"latest"`              |
| `cacheServerSpec.image.pullPolicy` | Image pull policy for the cache server.                                                                                              | string   | `"Always"`              |
| `cacheServerSpec.replicaCount`   | Number of replicas for the cache server pod.                                                                                          | integer  | `1`                     |
| `cacheServerSpec.containerPort`  | Port the cache server container is listening on.                                                                                       | integer  | `8000`                  |
| `cacheServerSpec.serviceType`    | Kubernetes service type for the cache server.                                                                                          | string   | `"ClusterIP"`           |
| `cacheServerSpec.servicePort`    | Port the cache server service will listen on.                                                                                          | integer  | `80`                    |
| `cacheServerSpec.resources`      | Resource requests and limits for the cache server container.                                                                          | map      | `{requests: {cpu: "1", memory: "2G"}, limits: {cpu: "2", memory: "4G"}}` |
| `cacheServerSpec.labels`         | Customized labels for the cache server deployment.                                                                                     | map      | `{environment: "cache", release: "cache"}` |
| `cacheServerSpec.strategy`       | Deployment strategy for the cache server pods.                                                                                       | map      | `{}`                    |
| `cacheServerSpec.startupProbe`   | Configuration for the startup probe of the cache server container.                                                                     | map      | `{initialDelaySeconds: 15, periodSeconds: 10, failureThreshold: 60, httpGet: {path: /health, port: 8000}}` |
| `cacheServerSpec.livenessProbe`  | Configuration for the liveness probe of the cache server container.                                                                    | map      | `{initialDelaySeconds: 15, periodSeconds: 10, failureThreshold: 3, httpGet: {path: /health, port: 8000}}` |
| `cacheServerSpec.maxUnavailablePodDisruptionBudget` | Configuration for the PodDisruptionBudget for the cache server pods.                                                            | string   | `""`                    |
| `cacheServerSpec.tolerations`    | Tolerations configuration for the cache server pods (when there are taints on nodes).                                                    | list     | `[]`                    |
| `cacheServerSpec.runtimeClassName` | RuntimeClassName configuration for the cache server pods.                                                                           | string   | `""`                    |
| `cacheServerSpec.schedulerName`  | SchedulerName configuration for the cache server pods.                                                                               | string   | `""`                    |
| `cacheServerSpec.securityContext`  | Pod-level security context configuration for the cache server pods.                                                                    | map      | `{}`                    |
| `cacheServerSpec.containerSecurityContext` | Container-level security context configuration for the cache server container.                                                    | map      | `{runAsNonRoot: false}` |
| `sharedStorage.enabled`          | Whether to enable shared storage for the models.                                                                                       | boolean  | `false`                 |
| `sharedStorage.size`             | Size of the shared storage volume.                                                                                                   | string   | `"100Gi"`               |
| `sharedStorage.accessModes`      | Access modes for the shared storage volume.                                                                                          | list     | `["ReadWriteOnce"]`     |
| `sharedStorage.storageClass`     | Storage class name for the shared storage volume.                                                                                    | string   | `"standard"`            |
| `sharedStorage.hostPath`         | Host path for the shared storage volume (for local testing only).                                                                    | string   | `""`                    |
| `sharedStorage.nfs.server`       | NFS server address for the shared storage volume.                                                                                      | string   | `""`                    |
| `sharedStorage.nfs.path`         | NFS export path for the shared storage volume.                                                                                         | string   | `""`                    |
