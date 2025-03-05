# vLLM Autoscaler for Production Stack on Kubernetes

* Author(s): Xiangfeng Zhu (@Romero027)
* Status: Draft
* Last updated: 2025-03-05

## Table of Contents

* [Summary](#summary)
* [Motivation](#motivation)
* [Proposal](#proposal)
* [Drawbacks](#drawbacks)
* [Alternatives](#alternatives)
* [Implementation Timeline / Phases](#implementation-timeline--phases)
* [References](#references)
<<<<<<< HEAD

=======
>>>>>>> 39130c8 (Add header)

## Summary

This proposal introduces a Kubernetes-native autoscaler designed specifically for vLLM workloads. Unlike traditional autoscalers such as the Horizontal Pod Autoscaler (HPA) and Vertical Pod Autoscaler (VPA), the vLLM Autoscaler dynamically adjusts the number of replicas based on vLLM-specific inference metrics. The autoscaler will utilize a Custom Resource Definition (CRD) to define autoscaling parameters and a Kubernetes controller to enforce them.

## Motivation

Kubernetes' built-in autoscalers—Horizontal Pod Autoscaler (HPA) and Vertical Pod Autoscaler (VPA)—are insufficient for vLLM workloads because they cannot scale based on custom inference metrics such as GPU utilization, request queue length, and response latency.

* HPA relies on CPU/memory utilization, which is irrelevant for GPU-bound inference workloads.
* VPA only adjusts resource requests/limits, but does not change the number of replicas dynamically.

Neither HPA nor VPA can react to inference-specific signals (e.g., queue depth). To address these limitations, the vLLM Autoscaler will use custom metrics to dynamically scale inference workloads based on real-time demand, ensuring optimal resource allocation and responsiveness.

### Goals

* Introduce a Kubernetes-native way to define autoscaling policies for vLLM deployments.
* Scale vLLM pods dynamically based on inference-specific metrics.
* Provide a declarative API to customize scaling behavior per model.

### Non-Goals

* Implementing a general-purpose autoscaler for non-vLLM workloads.
* Handling cluster-wide resource scheduling beyond vLLM pods.

## Proposal

### Proposed Changes

We propose a Kubernetes controller-based autoscaler with the following components:

1. **vLLMScalingPolicy CRD**: A custom resource definition for specifying autoscaling policies tailored to vLLM.
2. **vLLM Autoscaler Controller**: A control plane component that:
   * Monitors vLLM pods and collects inference-related metrics.
   * Adjusts pod replicas based on predefined policies.
3. **vLLM Metrics Exporter**: A Prometheus-compatible exporter that exposes GPU utilization, request queue length, and inference latency.

### Implementation Details/Notes/Constraints

The vLLM autoscaler follows a controller-based architecture with these key components:

* **vLLMScalingPolicy CRD**: Defines scaling thresholds based on GPU utilization, queue depth, and latency.
* **Autoscaler Controller**:
  * Watches `vLLMScalingPolicy` resources.
  * Fetches real-time GPU metrics from the vLLM Metrics Exporter.
  * Scales vLLM pods up or down based on policy-defined thresholds.
* **Metrics Exporter**: Exposes inference metrics to Kubernetes via Prometheus.

#### Custom Resources

The primary custom resource is the `vLLMScalingPolicy`, defined as follows:

```go
// vLLMScalingPolicySpec defines the desired state of vLLMScalingPolicy
type vLLMScalingPolicySpec struct {
    // ScaleTargetRef points to the scale-able resource that this autoscaler should target, e.g., Deployment.
    ScaleTargetRef corev1.ObjectReference `json:"scaleTargetRef"`

    // MinReplicas is the minimum number of replicas to which the target can be scaled down.
    MinReplicas int32 `json:"minReplicas"`

    // MaxReplicas is the maximum number of replicas to which the target can be scaled up.
    MaxReplicas int32 `json:"maxReplicas"`

    // ScalingRules defines the conditions under which scaling occurs.
    ScalingRules []ScalingRule `json:"scalingRules"`
}

// ScalingRule defines an individual rule for autoscaling decisions.
type ScalingRule struct {
    // Metric is the key metric used for scaling (e.g., gpu_utilization, queue_length, latency).
    Metric string `json:"metric"`

    // Threshold is the value at which scaling action should be taken.
    Threshold int `json:"threshold"`
}
```

#### Example CRD YAML

```yaml
apiVersion: autoscaler.production-stack/v1alpha1
kind: vLLMScalingPolicy
metadata:
  name: example-policy
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: meta-llama/Llama-2-70b-hf
  minReplicas: 1
  maxReplicas: 10
  scalingRules:
    - metric: "gpu_utilization"
      threshold: 75
    - metric: "queue_length"
      threshold: 10
    - metric: "latency"
      threshold: 1000
```

#### Interface Changes

1. **vLLM Helm Chart Modifications**:
   * Add `autoscaler.enabled` flag.
   * Expose GPU utilization metrics via Prometheus.
   * Provide annotation-based discovery for autoscaler.

2. **vLLM Autoscaler API**:
   * `GetScalingMetrics(pod)` - Fetches real-time inference metrics.
   * `AdjustReplicas(model, targetReplicas)` - Adjusts vLLM replicas dynamically.
   * `GetScalingPolicy(model)` - Fetches the scaling policy for a given model.

### Test Plans

* Unit tests for controller logic.
* End-to-end tests for scaling behavior validation.
* Performance tests simulating bursty workloads.

## Drawbacks

* **Increased Complexity**: Adds another component to Kubernetes.
* **Potential Overhead**: Frequent scaling may introduce latency.
* **Failure Modes**: Scaling decisions must be robust to noisy metrics.

## Alternatives

* **Kubernetes HPA/VPA**: Lacks inference-specific metrics support.
* **Do Nothing**: Requires manual adjustments.

## Implementation Timeline / Phases

### Phase 1: Core Infrastructure

* Implement `vLLMScalingPolicy` CRD.
* Develop the autoscaler controller.
* Integrate Prometheus metrics exporter.

### Phase 2: Advanced Metrics & Optimization

* Implement different scaling policies.

### Phase 3: Production Readiness

* Full test coverage.
* Performance tuning.
* Documentation.

## References

* [Kubernetes Custom Resource Definitions](https://kubernetes.io/docs/concepts/extend-kubernetes/api*extension/custom-resources/)
* [Kubernetes Autoscaling](https://kubernetes.io/docs/concepts/workloads/autoscaling/)
