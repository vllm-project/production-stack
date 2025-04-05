# Tutorial: Prefill-Decode (PD) Disaggregation with LMCache

## Introduction

This tutorial demonstrates how to set up a Prefill-Decode (PD) disaggregated architecture using vLLM and LMCache. In this setup, the model serving is split into two specialized components:

- Prefill nodes: Handle the initial prompt processing and KV cache generation
- Decode nodes: Focus on token generation using the KV cache from prefill nodes

This architecture can improve resource utilization and throughput by allowing each component to specialize in its task. The KV cache is shared between prefill and decode nodes using LMCache.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Step 1: Understanding the PD Disaggregation Configuration](#step-1-understanding-the-pd-disaggregation-configuration)
3. [Step 2: Deploying the Helm Chart](#step-2-deploying-the-helm-chart)
4. [Step 3: Verifying the Installation](#step-3-verifying-the-installation)
5. [Step 4: Testing the PD Disaggregation Setup](#step-4-testing-the-pd-disaggregation-setup)

## Prerequisites

- Completion of the following tutorials:
  - [00-install-kubernetes-env.md](00-install-kubernetes-env.md)
  - [01-minimal-helm-installation.md](01-minimal-helm-installation.md)
  - [02-basic-vllm-config.md](02-basic-vllm-config.md)
- A Kubernetes environment with GPU support
- Basic understanding of LMCache and KV cache sharing

## Step 1: Understanding the PD Disaggregation Configuration

The configuration file `tutorials/assets/values-12-pd-disaggregation.yaml` sets up a complete PD disaggregation deployment example. Let's examine its key components:

1. **Serving Engine Configuration**:
   - Two model specifications:
     - `mistral-prefill`: Handles prompt processing and KV cache generation
     - `mistral-decode`: Specializes in token generation
   - Each node has its own resource allocation and LMCache configuration

2. **Router Configuration**:
   - Uses a specialized router (`1nfinity/vllm_router`) with `disagg_prefill` routing logic
   - Routes requests between prefill and decode nodes
   - Monitors engine health and request statistics

3. **Cache Server Configuration**:
   - Provides shared KV cache storage between prefill and decode nodes
   - Uses the naive serialization format

## Step 2: Deploying the Helm Chart

Deploy the Helm chart using the PD disaggregation configuration:

```bash
helm install vllm vllm/vllm-stack -f tutorials/assets/values-12-pd-disaggregation.yaml
```

## Step 3: Verifying the Installation

1. Check that all components are running:

   ```bash
   kubectl get pods
   ```

   You should see:
   - Prefill node pods
   - Decode node pods
   - Router pod
   - Cache server pod

2. Verify the LMCache configuration in the prefill node logs:

   ```bash
   kubectl logs -f <prefill-pod-name>
   ```

   Look for LMCache initialization messages and KV producer role confirmation.

3. Verify the LMCache configuration in the decode node logs:

   ```bash
   kubectl logs -f <decode-pod-name>
   ```

   Look for LMCache initialization messages and KV consumer role confirmation.

## Step 4: Testing the PD Disaggregation Setup

1. Forward the router service port:

   ```bash
   kubectl port-forward svc/vllm-router-service 30080:80
   ```

2. Run a simple benchmark script to test the performance of P/D disaggregation:

   ```bash
   bash benchmarks/multi-round-qa/run_pd.sh mistralai/Mistral-7B-Instruct-v0.2 http://localhost:30080/v1 stack
   ```

3. Monitor the logs of both prefill and decode nodes to observe:
   - Prefill node generating KV cache
   - Decode node consuming the KV cache
   - Cache server handling the KV cache transfer

## Conclusion

This tutorial demonstrated how to set up a Prefill-Decode disaggregated architecture using vLLM and LMCache. This setup allows for:

- Specialized resource allocation for different stages of inference
- Improved throughput through parallel processing
- Efficient KV cache sharing between components

You can further optimize this setup by:

- Adjusting resource allocations based on workload patterns
- Fine-tuning the LMCache configuration
- Scaling the number of prefill or decode nodes independently
