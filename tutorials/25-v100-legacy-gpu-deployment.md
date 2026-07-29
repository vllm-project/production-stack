# Tutorial: Deploying on Tesla V100 and Other Legacy (Volta, CC 7.0) GPUs

## Introduction

This tutorial is for users who run the vLLM Production Stack on **Volta-generation NVIDIA GPUs** such as the Tesla V100 (CUDA Compute Capability 7.0). Newer prebuilt vLLM images (`vllm/vllm-openai:latest`, vLLM v0.9+) **dropped support for Compute Capability below 8.0**, so a V100 deployment that works on Ampere/Hopper out of the box will fail on Volta with errors like:

```plaintext
RuntimeError: CUDA error: no kernel image is available for execution on the device
```

The failures are silent or cryptic, and none of them are documented in the existing tutorials. This guide walks through the exact image pin and flags needed to get single-GPU and multi-GPU (tensor-parallel) deployments running on V100 hardware, plus a reference table of the errors we hit and how we fixed them.

All configurations here were validated on a bare-metal OpenShift (OKD 4.19, Kubernetes v1.32.8) cluster with `vllm-stack-0.1.11`, on Tesla V100 SXM2 16GB nodes, serving `Qwen2.5-0.5B/7B/14B-Instruct`.

## Table of Contents

- [Tutorial: Deploying on Tesla V100 and Other Legacy (Volta, CC 7.0) GPUs](#tutorial-deploying-on-tesla-v100-and-other-legacy-volta-cc-70-gpus)
  - [Introduction](#introduction)
  - [Table of Contents](#table-of-contents)
  - [Prerequisites](#prerequisites)
  - [Why V100 Needs Special Handling](#why-v100-needs-special-handling)
  - [Step 1: Single GPU Deployment (TP=1)](#step-1-single-gpu-deployment-tp1)
  - [Step 2: Multi-GPU Deployment (TP=2 and TP=4)](#step-2-multi-gpu-deployment-tp2-and-tp4)
  - [Step 3: Common Errors and Fixes](#step-3-common-errors-and-fixes)
  - [Step 4: Benchmark Reference Numbers](#step-4-benchmark-reference-numbers)
  - [Conclusion](#conclusion)

## Prerequisites

- A Kubernetes environment with GPU support, as set up in the [00-install-kubernetes-env tutorial](00-install-kubernetes-env.md).
- One or more nodes with **Tesla V100 (or other Volta, CC 7.0) GPUs**, with the NVIDIA device plugin and `nvidia` runtime class installed.
- Helm installed on your system.
- Access to a HuggingFace token (`HF_TOKEN`) if your model is gated. The Qwen2.5 models used here are public.
- Familiarity with [01-minimal-helm-installation.md](01-minimal-helm-installation.md) and [02-basic-vllm-config.md](02-basic-vllm-config.md).

## Why V100 Needs Special Handling

The Tesla V100 is a Volta GPU with **CUDA Compute Capability 7.0**. Modern vLLM builds and kernels increasingly target Ampere (CC 8.0) and newer, which leads to several hard constraints on Volta:

- **No native BF16 datapath.** Volta has no hardware `bfloat16` support. If vLLM loads a model with the default `dtype=bfloat16`, kernel launches fail with `no kernel image is available for execution on the device`. You must run in FP16 by setting `dtype: "half"`.
- **No FP8.** FP8 weights/KV cache (Hopper-era features) are unavailable on Volta. Stick to FP16.
- **vLLM V1 engine assumes CC ≥ 8.0.** The newer V1 engine and its CUDA-graph / FlashAttention paths are not reliable on Volta. You must fall back to the legacy **V0 engine** (`v0: "1"`, which the chart maps to `VLLM_USE_V1=0`).
- **Attention backend.** On Volta the supported attention path is XFormers (FlashAttention-2/3 require Ampere+). The V0 engine selects an appropriate Volta-compatible backend automatically once you are on the pinned image and FP16.
- **The `latest` image dropped Volta.** As of vLLM **v0.9+**, the published `vllm/vllm-openai:latest` image no longer ships kernels compiled for CC < 8.0. You must **pin the image tag to `v0.8.5`**, the last release with Volta-compatible CUDA kernels.

Putting it together, every V100 deployment in this tutorial pins `tag: "v0.8.5"`, sets `dtype: "half"`, forces `v0: "1"`, passes `--enforce-eager` (CUDA-graph capture is unstable on Volta with this image), and sets `VLLM_ENABLE_CUDA_COMPATIBILITY=1` to allow PTX JIT for forward compatibility.

## Step 1: Single GPU Deployment (TP=1)

Start with the smallest model to confirm the image and flags are correct before scaling out. The example file is [`tutorials/assets/values-25-v100-single-gpu.yaml`](assets/values-25-v100-single-gpu.yaml), serving `Qwen2.5-0.5B-Instruct` on a single V100.

```yaml
servingEngineSpec:
  runtimeClassName: "nvidia"
  strategy:
    type: Recreate
  modelSpec:
  - name: "qwen05b"
    repository: "vllm/vllm-openai"
    tag: "v0.8.5"
    modelURL: "Qwen/Qwen2.5-0.5B-Instruct"
    replicaCount: 1
    requestCPU: 6
    requestMemory: "16Gi"
    requestGPU: 1
    pvcStorage: "20Gi"
    pvcAccessMode:
      - ReadWriteOnce
    vllmConfig:
      dtype: "half"
      v0: "1"
      tensorParallelSize: 1
      maxModelLen: 16384
      gpuMemoryUtilization: 0.9
      extraArgs:
        - "--enforce-eager"
    env:
      - name: VLLM_ENABLE_CUDA_COMPATIBILITY
        value: "1"
    nodeSelectorTerms:
      - matchExpressions:
          - key: "kubernetes.io/hostname"
            operator: "In"
            values:
              - "gpu-node-01"
```

**Why each V100-specific field is needed:**

- **`tag: "v0.8.5"`** — the last image with kernels compiled for Compute Capability 7.0. `latest` (v0.9+) will not run on Volta.
- **`vllmConfig.dtype: "half"`** — Volta has no BF16 hardware. Forcing FP16 avoids the `no kernel image available` crash you get from the default `bfloat16`.
- **`vllmConfig.v0: "1"`** — selects the legacy V0 engine (the chart sets `VLLM_USE_V1=0`). The V1 engine assumes CC ≥ 8.0.
- **`vllmConfig.tensorParallelSize: 1`** — a single 16GB V100 is enough for the 0.5B model.
- **`extraArgs: ["--enforce-eager"]`** — disables CUDA-graph capture, which is unreliable on Volta with this image. The chart has no `enforceEager` field, so this must be passed through `extraArgs`.
- **`env: VLLM_ENABLE_CUDA_COMPATIBILITY=1`** — enables PTX JIT so kernels can run on Volta via CUDA forward compatibility.
- **`nodeSelectorTerms`** — pins the pod to a known V100 host via node affinity. Use `nodeSelectorTerms`, **not** `nodeSelector`; the chart only renders `nodeSelectorTerms`.

Deploy it:

```bash
helm repo add vllm https://vllm-project.github.io/production-stack
helm install vllm vllm/vllm-stack -f tutorials/assets/values-25-v100-single-gpu.yaml
```

Verify the pod is running and check the logs to confirm the V0 engine and FP16 are active:

```bash
kubectl get pods
kubectl logs -f <vllm-pod-name> | grep -Ei "dtype|engine|compute capability"
```

Refer to Step 3 in [01-minimal-helm-installation.md](01-minimal-helm-installation.md) for querying the deployed service.

## Step 2: Multi-GPU Deployment (TP=2 and TP=4)

Models that do not fit in a single 16GB V100 must be sharded across GPUs with tensor parallelism. A 7B model in FP16 needs ~14GB just for weights (leaving no room for the KV cache), so it needs **TP=2** minimum; a 14B model needs **TP=4**.

The example files are [`tutorials/assets/values-25-v100-multi-gpu-tp2.yaml`](assets/values-25-v100-multi-gpu-tp2.yaml) (`Qwen2.5-7B-Instruct`, TP=2) and [`tutorials/assets/values-25-v100-multi-gpu-tp4.yaml`](assets/values-25-v100-multi-gpu-tp4.yaml) (`Qwen2.5-14B-Instruct`, TP=4).

TP=2 snippet:

```yaml
servingEngineSpec:
  runtimeClassName: "nvidia"
  strategy:
    type: Recreate
  modelSpec:
  - name: "qwen7b"
    repository: "vllm/vllm-openai"
    tag: "v0.8.5"
    modelURL: "Qwen/Qwen2.5-7B-Instruct"
    replicaCount: 1
    requestCPU: 8
    requestMemory: "32Gi"
    requestGPU: 2
    pvcStorage: "50Gi"
    pvcAccessMode:
      - ReadWriteOnce
    vllmConfig:
      dtype: "half"
      v0: "1"
      tensorParallelSize: 2
      maxModelLen: 8192
      gpuMemoryUtilization: 0.9
      extraArgs:
        - "--enforce-eager"
    env:
      - name: VLLM_ENABLE_CUDA_COMPATIBILITY
        value: "1"
    shmSize: "4Gi"
    nodeSelectorTerms:
      - matchExpressions:
          - key: "kubernetes.io/hostname"
            operator: "In"
            values:
              - "gpu-node-01"
```

In addition to the single-GPU requirements, multi-GPU adds the following:

- **`tensorParallelSize` must live in `vllmConfig`, NOT in `extraArgs`.** This is the easiest mistake to make. The chart renders `vllmConfig.tensorParallelSize` into the `--tensor-parallel-size` flag for you. If you instead add `--tensor-parallel-size` (or `--tensor_parallel_size`) to `extraArgs`, the value is **silently ignored**, tensor parallelism stays at 1, and the pod then OOMs while loading the model. Always set it in `vllmConfig`.
- **`shmSize: "4Gi"`** — tensor-parallel all-reduce uses NCCL, which communicates between the per-GPU worker processes through `/dev/shm`. The Kubernetes default `/dev/shm` (64Mi) is too small for multi-GPU NCCL and causes init hangs or bus errors. The chart already mounts a 20Gi `tmpfs` whenever `tensorParallelSize` is set, so the default is sufficient; here we pin a smaller, resource-friendly `4Gi` that is still plenty for these models.
- **`strategy.type: Recreate`** — set at the `servingEngineSpec` level. This is required on GPU nodes. With the default `RollingUpdate`, on a redeploy Kubernetes creates the new pod **before** terminating the old one. The new pod then waits for GPUs the old pod still holds, while the old pod is not torn down until the new one is `Ready` — a **deadlock** that leaves both pods `Pending` until you manually delete the old one. `Recreate` tears the old pod down first, releasing the GPUs.

For **TP=4**, the same pattern applies with `requestGPU: 4` and `tensorParallelSize: 4` (see the TP=4 asset file).

**NVLink topology awareness.** Tensor parallelism generates all-reduce traffic on every layer, so inter-GPU bandwidth matters. Place the parallel group on directly NVLink-connected GPUs:

- On our cluster, `gpu-node-01` has 3x V100 in an NVLink "NV2" triangle, so any two GPUs on that host are directly NVLink-connected — a good fit for a **TP=2** pair.
- `gpu-node-02` has 4x V100 in a **full NVLink mesh** (every GPU connected to every other), which is what **TP=4** wants.

If the TP group spans GPUs that are only connected over PCIe, the all-reduce falls back to PCIe and throughput drops sharply. You can inspect the topology on a node with `nvidia-smi topo -m`.

Deploy and verify the same way as Step 1:

```bash
helm install vllm vllm/vllm-stack -f tutorials/assets/values-25-v100-multi-gpu-tp2.yaml
kubectl get pods
```

## Step 3: Common Errors and Fixes

These are the failures we hit on our test cluster and the exact fix for each.

| Symptom / Error | Root Cause | Fix |
| --- | --- | --- |
| `RuntimeError: CUDA error: no kernel image is available for execution on the device` | Model loaded as `bfloat16` (the default); Volta has no BF16 kernels. | Set `vllmConfig.dtype: "half"`. |
| `CUDA error: invalid device function` | Using `vllm/vllm-openai:latest` (v0.9+), which dropped CC < 8.0 kernels. | Pin `tag: "v0.8.5"`. |
| Pod OOM / killed while loading a 7B+ model on a single GPU | The model does not fit in 16GB of V100 memory at TP=1. | Use TP=2 (7B) or TP=4 (14B) via `requestGPU` + `tensorParallelSize`. |
| Pod scheduled on the wrong (non-V100) node | Used `nodeSelector`, which this chart does not render. | Use `nodeSelectorTerms` (node affinity) instead. |
| Both old and new pods stuck `Pending` after a redeploy | Default `RollingUpdate` starts the new pod before the old one frees its GPUs — GPU deadlock. | Set `servingEngineSpec.strategy.type: Recreate`. |
| Engine reports `tensor_parallel_size=1` even though you set it | `--tensor-parallel-size` was placed in `extraArgs`, where it is silently ignored. | Set `tensorParallelSize` inside `vllmConfig`. |
| NCCL init hang or bus error on multi-GPU startup | `/dev/shm` too small (Kubernetes default 64Mi). | Set `shmSize` (e.g. `4Gi`); the chart's `20Gi` default also works. |

## Step 4: Benchmark Reference Numbers

The following throughput numbers are from real runs on our V100 SXM2 16GB nodes with the configurations in this tutorial. Use them as a sanity check that your deployment is in the right ballpark, not as guaranteed performance.

| Model | TP | Approx. throughput | Notes |
| --- | --- | --- | --- |
| `Qwen2.5-0.5B-Instruct` | 1 | ~435 tok/s/GPU | Single V100, fits easily. |
| `Qwen2.5-7B-Instruct` | 2 | ~155 tok/s/GPU | NVLink pair on `gpu-node-01`. |
| `Qwen2.5-14B-Instruct` | 4 | ~56 tok/s/GPU | Full NVLink mesh on `gpu-node-02`. |

Per-GPU throughput drops as the tensor-parallel degree grows because all-reduce communication overhead increases with the size of the TP group — this is expected, and is exactly why NVLink topology matters.

For interactive serving, regardless of model size, plan for roughly **8–16 concurrent requests per deployment** before latency-sensitive (interactive SLO) requests start to degrade. Scale out with additional replicas (and additional GPUs) rather than pushing a single deployment past that range.

## Conclusion

Volta-generation GPUs like the Tesla V100 are still capable inference accelerators, but they require deliberate configuration on the modern vLLM Production Stack: pin the image to `v0.8.5`, run in FP16 (`dtype: "half"`), force the V0 engine (`v0: "1"`), use `--enforce-eager`, and set `VLLM_ENABLE_CUDA_COMPATIBILITY=1`. For multi-GPU, keep `tensorParallelSize` in `vllmConfig`, set an adequate `shmSize` for NCCL, use the `Recreate` strategy to avoid GPU deadlocks, and align the tensor-parallel group with the NVLink topology. With these settings, single-GPU and tensor-parallel deployments run reliably on CC 7.0 hardware.
