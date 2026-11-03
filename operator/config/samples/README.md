# Operator resource requirements

`VLLMRuntime`, `VLLMRouter`, and `CacheServer` resources accept independent
CPU and memory requests and limits:

```yaml
resources:
  requests:
    cpu: "1"
    memory: "4Gi"
  limits:
    cpu: "2"
    memory: "8Gi"
```

The flat `cpu`, `memory`, `gpu`, and `gpuType` fields remain supported for
backward compatibility. Flat CPU and memory values are applied to both requests
and limits; each non-empty nested CPU or memory value overrides the matching
flat value for that side. When no matching flat value or request is set, the
operator copies a CPU or memory limit into the request to match Kubernetes
defaulting. Runtime sidecars keep their existing implicit CPU and memory
defaults unless the corresponding nested value overrides them.

GPU remains configured through the shared flat `gpu` and `gpuType` fields, and
the operator applies the same GPU value to requests and limits. The `gpuType`
defaults to `nvidia.com/gpu`.

See the manifests in this directory for examples. The autoscaling sample keeps
using flat resource fields to demonstrate the backward-compatible form.
