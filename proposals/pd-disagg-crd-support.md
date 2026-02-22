# Summary

Prefill and Decode are two phases of LLM inference. Prefill is compute-bound, Decode is memory-bound. Disaggregated serving separates them onto different node pools for better resource utilization.

## Motivation

Current PD disaggregation in production-stack is only configurable via Helm values with manual multi-modelSpec setup. There is no CRD-level support for declaring a PD topology.

## Goal

- Support K8S-Native PD Disaggregated Serving with CRD
- Extensible to XpYd
- Consider RBAC, Namespace, observability, persistence

## Proposal

CRD + Controller

### Architecture

### Request Flow

### Control Flow

### Implementation Plan

#### Custom Resource

```yaml
spec:
  enablePDDisaggregation: true
  topology:
    prefill:
      deploymentConfig:
        replicas: 2
      lmCacheConfig:
        kvRole: "kv_producer"
        nixlRole: "sender"
    decode:
      deploymentConfig:
        replicas: 2
      lmCacheConfig:
        kvRole: "kv_consumer"
        nixlRole: "receiver"
```

## Alternative Approaches

### Helm + CRD

## References

- [Tutorial 16: Disaggregated Prefill](https://github.com/vllm-project/production-stack/blob/main/tutorials/16-disagg-prefill.md)
