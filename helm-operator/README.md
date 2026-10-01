# vllm-stack-operator

Helm chart for the [vLLM production stack](https://github.com/vllm-project/production-stack) operator.

One `helm install` deploys everything needed to run an inference service:

1. The CRDs (`VLLMRuntime`, `VLLMRouter`, `CacheServer`, `LoraAdapter`) from the
   chart's `crds/` directory,
2. The operator controller manager (Deployment + ServiceAccount + RBAC),
3. The custom resources themselves, rendered from values — by default a
   `VLLMRuntime` (vLLM engine) and a `VLLMRouter` (router), already wired
   together. The operator then creates the engine/router Deployments, Services,
   PVCs and service accounts.

The chart is self-contained and does not modify the main `helm/` chart. The
original manual installation path (`kubectl create -f operator/config/default.yaml`
plus applying samples) remains fully supported.

## Install

```bash
helm install vllm-stack ./helm-operator -n production-stack-system --create-namespace
```

This is equivalent to `kubectl create -f operator/config/default.yaml` followed by
applying the `vllmruntime` and `vllmrouter` samples. Watch the rollout:

```bash
kubectl get pods -n production-stack-system
kubectl get vllmruntime,vllmrouter -n production-stack-system
```

When the engine pods are ready, port-forward the router and send a request:

```bash
kubectl port-forward svc/vllm-stack-vllm-stack-operator-router 30080:80 -n production-stack-system
curl http://localhost:30080/v1/models
```

## Configure the inference service

Everything is controlled through values. The `spec` blocks below are passed
through verbatim to the custom resources, so any field of the CRD schema can be
set without waiting for the chart to add an explicit knob.

Use your own model and image:

```yaml
vllmRuntimes:
  - name: ""
    spec:
      model:
        modelURL: "Qwen/Qwen2.5-7B-Instruct"
        hfTokenSecret:
          hfTokenSecretName: "huggingface-token"
          hfTokenKeyName: "token"
      vllmConfig:
        tensorParallelSize: 2
      deploymentConfig:
        image:
          registry: "docker.io"
          name: "lmcache/vllm-openai"
          tag: "latest"
        replicas: 2
```

Enable the LMCache cache server and point the runtime at it:

```yaml
cacheServer:
  enabled: true
vllmRuntimes:
  - name: ""
    spec:
      lmCacheConfig:
        enabled: true
        remoteUrl: "lm://vllm-stack-vllm-stack-operator-cacheserver.production-stack-system.svc.cluster.local:80"
```

Serve **multiple models** behind the single router with one `vllmRuntimes`
entry per model — see [Serve multiple models](#serve-multiple-models).

## Serve multiple models

One router can serve any number of models. The pattern: **one `vllmRuntimes`
entry per model**, sparse specs deep-merged over `vllmRuntimeDefaults`.

```yaml
# Shared configuration for every model
vllmRuntimeDefaults:
  vllmConfig:
    port: 8000
  storageConfig:
    enabled: true
    accessMode: "ReadWriteMany"

# One entry per model — only the differences
vllmRuntimes:
  - spec:                        # defaults to <release>-...-runtime
      model:
        modelURL: "deepseek-ai/DeepSeek-R1-Distill-Llama-70B"
      deploymentConfig:
        resources: {cpu: "16", memory: "64Gi", gpu: "8"}   # heavy model, 1 replica
  - spec:                        # defaults to ...-runtime-1
      model:
        modelURL: "Qwen/Qwen2.5-7B-Instruct"
      deploymentConfig:
        replicas: 3              # same model, more throughput → replicas
```

Scaling rule of thumb: **more of the same model → raise that entry's
`deploymentConfig.replicas`; a different model or resource profile → add
another entry.** Autoscaling ([KEDA](#values) prerequisites apply) is
configured per entry via `spec.autoscalingConfig`, so each model scales on its
own thresholds.

How it works under the hood:

1. The chart renders one `VLLMRuntime` CR per entry and labels each with
   `production-stack.vllm.ai/runtime-set: <fullname>`.
2. The operator copies CR labels onto the engine pods, so every engine of this
   release carries the shared label.
3. The `VLLMRouter`'s `k8sLabelSelector` defaults to that label, so the router
   discovers **all** engines of the release and routes each request by its
   `model` field (strategies like roundrobin apply among the replicas serving
   that model).

What is per-model versus shared:

| Per model (per `vllmRuntimes` entry) | Shared per release |
|---|---|
| engine Deployment, replicas, resources, image | operator |
| **its own PVC** (named after the CR) and Service | router (single) |
| autoscaling (`autoscalingConfig`) | CacheServer (LMCache, single) |
| model URL, vLLM flags, LoRA settings | CRDs |

Note: each model's replicas share that model's own PVC, so the
[ReadWriteMany requirement](#shared-storage-pvc--the-readwritemany-requirement)
applies **per model**.

Clients send everything to the same router endpoint and pick the model by name:

```bash
kubectl port-forward svc/<release>-vllm-stack-operator-router 30080:80 -n production-stack-system
curl http://localhost:30080/v1/models
curl http://localhost:30080/v1/chat/completions -H "Content-Type: application/json" \
  -d '{"model": "deepseek-ai/DeepSeek-R1-Distill-Llama-70B", "messages": [{"role": "user", "content": "hi"}]}'
curl http://localhost:30080/v1/chat/completions -H "Content-Type: application/json" \
  -d '{"model": "Qwen/Qwen2.5-7B-Instruct", "messages": [{"role": "user", "content": "hi"}]}'
```

## Shared storage (PVC) — the ReadWriteMany requirement

The operator creates **one** PVC per `VLLMRuntime` resource (named after the CR)
and mounts it at `/data` in **every** engine pod. Model weights and the Hugging
Face cache live there, so replicas share one copy instead of each re-downloading
the model.

All replicas mounting the same PVC requires `accessMode: ReadWriteMany` (RWX) —
and **many StorageClasses do not support RWX**:

| StorageClass backend | RWX support |
|----------------------|-------------|
| NFS, CephFS (CephFS-CSI), JuiceFS, SeaweedFS | yes |
| AWS EFS, GCP Filestore, Azure Files (non-premium) | yes |
| Longhorn | yes (via share-manager, slower) |
| `local-path` / host-path | no (single node only) |
| Cloud block storage: AWS gp2/gp3/ebs, GCP pd-standard/pd-balanced, Azure managed disk | **no** |

Check what you have and whether a class can do RWX:

```bash
kubectl get sc
kubectl get sc <name> -o jsonpath='{.provisioner}'
```

What happens with an RWO-only class:

- all replicas land on the **same node** → it works (RWO permits same-node
  mounts by pods of the same node);
- replicas spread across **multiple nodes** → extra pods stick in `Pending`
  with `Multi-Attach error for volume ... Volume is already exclusively
  attached to one node`.

Recommended settings when running `replicas > 1` across nodes:

```yaml
vllmRuntime:
  spec:
    storageConfig:
      storageClassName: "nfs-client"   # an RWX-capable class in your cluster
      accessMode: ReadWriteMany
      size: "50Gi"
```

If you have no RWX-capable class, pick one of:

- `deploymentConfig.replicas: 1` (single replica needs no shared mount);
- pin all engine pods to one node with `deploymentConfig.nodeSelector` /
  affinity (RWO then works);
- `storageConfig.enabled: false` — no PVC; each pod downloads the model into
  its own container filesystem (slower startup, no cache sharing).

Note: the chart always sets `accessMode: ReadWriteMany` explicitly. If the
field were omitted, the CRD schema defaults it to `ReadWriteMany` as well, but
the operator falls back to `ReadWriteOnce` for CRs created before that
defaulting existed — keep the field set.

## Values

| Key | Default | Description |
|-----|---------|-------------|
| `replicaCount` | `1` | Number of operator replicas (leader election allows more than one) |
| `image.repository` | `lmcache/production-stack-operator` | Operator image repository (`ghcr.io/vllm-project/production-stack-operator` also published) |
| `image.tag` | `latest` | Operator image tag; pin to a release tag or commit SHA in production |
| `image.pullPolicy` | `IfNotPresent` | Image pull policy |
| `imagePullSecrets` | `[]` | Existing image pull secrets |
| `nameOverride` / `fullnameOverride` | `""` | Override resource names |
| `serviceAccount.create` | `true` | Create a dedicated service account |
| `serviceAccount.name` | `""` | Service account name (generated when empty) |
| `rbac.create` | `true` | Create the ClusterRole/Role and bindings |
| `leaderElection.enabled` | `true` | Enable leader election |
| `metrics.enabled` | `false` | Expose the operator metrics endpoint over plain HTTP |
| `metrics.service.port` | `8443` | Metrics port (service and `--metrics-bind-address`) |
| `metrics.serviceMonitor.enabled` | `false` | Create a ServiceMonitor for Prometheus Operator auto-discovery (requires `metrics.enabled=true` and the prometheus-operator CRDs) |
| `metrics.serviceMonitor.additionalLabels` | `{release: kube-prometheus-stack}` | Labels to match your Prometheus `serviceMonitorSelector`; default matches a kube-prometheus-stack release named `kube-prometheus-stack` |
| `metrics.serviceMonitor.interval` / `scrapeTimeout` | `30s` / `10s` | Scrape interval and timeout |
| `metrics.serviceMonitor.honorLabels` / `metricRelabelings` / `relabelings` | `false` / `[]` / `[]` | Extra scrape tuning, same knobs as the main chart's ServiceMonitors |
| `networkPolicy.enabled` | `false` | Restrict metrics scraping to namespaces labeled `metrics: enabled` (mirrors `operator/config/network-policy`; requires a NetworkPolicy-enforcing CNI) |
| `resources` | `500m/128Mi` limits, `10m/64Mi` requests | Operator resources, mirrors `operator/config/manager` |
| `nodeSelector` / `affinity` / `tolerations` | `{}` / `{}` / `[]` | Operator pod scheduling |
| `extraEnv` | `[]` | Extra environment variables for the operator |
| `extraArgs` | `[]` | Extra manager flags, e.g. `["--zap-log-level=debug"]` |
| `vllmRuntimeDefaults` | see `values.yaml` | Shared `VLLMRuntimeSpec` defaults (model, vllmConfig, lmCacheConfig, deploymentConfig, storageConfig, autoscalingConfig) deep-merged into every entry below |
| `vllmRuntimes` | one empty entry | List of `VLLMRuntime` resources — **one entry per model**, sparse specs deep-merged over `vllmRuntimeDefaults`; entry 0 defaults to `<release>-...-runtime`, entry i to `...-runtime-<i>` |
| `vllmRouter.enabled` | `true` | Render a `VLLMRouter` resource in front of the engine |
| `vllmRouter.name` | `""` | Resource name, defaults to `<release>-vllm-stack-operator-router` |
| `vllmRouter.spec.k8sLabelSelector` | `""` | Defaults to the chart's shared runtime-set label, so the router serves every model of the release |
| `vllmRouter.spec` | see `values.yaml` | Verbatim `VLLMRouterSpec` (replicas, routingLogic, image, resources, env, ...) |
| `cacheServer.enabled` | `false` | Render a `CacheServer` resource (LMCache server) |
| `cacheServer.spec` | see `values.yaml` | Verbatim `CacheServerSpec` |
| `loraAdapters` | `[]` | List of `{name, spec}` entries, each rendered as a `LoraAdapter` |

## CRD lifecycle (important)

Helm installs the CRDs from `crds/` on the first `helm install` (skipping any that
already exist), but **never upgrades or deletes them** on `helm upgrade` /
`helm uninstall`. This is deliberate: deleting a CRD deletes every custom resource
of that kind in the cluster.

When upgrading to an operator version that ships CRD changes, apply them
manually:

```bash
kubectl apply --server-side -f helm-operator/crds/
```

## Development

The CRDs in `crds/` duplicate `operator/config/crd/bases/` on purpose: Helm
charts must be self-contained once packaged (the `crds/` directory cannot
reference files outside the chart). Keep the two in sync with the provided
make targets — never edit `helm-operator/crds/` by hand:

```bash
cd operator
make helm-crds        # regenerate (controller-gen) and copy into the chart
make helm-crds-check  # fail if the copies drifted (for CI)
```

Run the chart unit tests (requires [helm-unittest](https://github.com/helm-unittest/helm-unittest)):

```bash
helm unittest helm-operator
```

## Uninstall

```bash
helm uninstall vllm-stack -n production-stack-system
```

Helm removes the operator and the custom resources. The engine/router workloads
the operator created are garbage-collected with them (the operator sets owner
references on everything it creates). The CRDs themselves are kept; delete them
explicitly if you want to remove every trace:

```bash
kubectl delete -f helm-operator/crds/
```

Caveats:

- `LoraAdapter` resources carry a finalizer. If the operator pod is gone before
  it processes their deletion, those CRs (and a namespace containing them) can
  stick in `Terminating`. Re-run the operator once, or strip the finalizer:
  `kubectl patch loraadapter <name> -p '{"metadata":{"finalizers":[]}}' --type=merge`.
- The chart creates cluster-scoped objects (ClusterRole, ClusterRoleBinding)
  named after the release. Run at most one release of this chart per cluster,
  or override `fullnameOverride` per release.
