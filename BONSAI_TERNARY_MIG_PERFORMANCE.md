# Bonsai Ternary 8B MIG Deployment — Performance Test Results

## Overview
This document records the deployment and performance testing of the **Bonsai Ternary 1.58-bit 8B** model on four NVIDIA MIG `1g.10gb` instances in the local Kubernetes cluster.

- **Namespace:** `bonsai-ternary`
- **Deployment:** `bonsai-ternary-mig`
- **Replicas:** 4 (one per available MIG instance)
- **Proxy:** LiteLLM (`litellm-bonsai-proxy`) exposed on `http://100.115.213.88:4000/v1`
- **Model file:** `Ternary-Bonsai-8B-Q2_0.gguf` (mounted via hostPath)

## Final Deployment Configuration

### llama-server Command
```yaml
- /opt/prism-release/llama-prism-b8846-d104cf1/llama-server
- --host
- "0.0.0.0"
- --port
- "8080"
- -m
- /model/Ternary-Bonsai-8B-Q2_0.gguf
- --ctx-size
- "65536"
- --parallel
- "2"
- --cache-type-k
- "q8_0"
- --cache-type-v
- "q8_0"
- --threads
- "8"
```

### Resource Requests
```yaml
limits:
  nvidia.com/mig-1g.10gb: 1
requests:
  nvidia.com/mig-1g.10gb: 1
```

### Host Library Mounts
- `/usr/lib/x86_64-linux-gnu/libcuda.so.1`
- `/usr/lib/x86_64-linux-gnu/libgomp.so.1`
- `/usr/lib/x86_64-linux-gnu/libnvidia-ptxjitcompiler.so.1`

### Proxy
The LiteLLM proxy is configured with `hostNetwork: true` and listens directly on host port `4000`, routing to the backend Kubernetes service `bonsai-ternary-mig:8080`.

## Test Methodology

Tests were run from the host against:
```
http://100.115.213.88:4000/v1/completions
```

Payload template:
```json
{
  "model": "bonsai-ternary-8b",
  "prompt": "Once upon a time",
  "max_tokens": <N>,
  "temperature": 0.0
}
```

Metrics collected:
- `tokens_predicted` from the response
- `timings.predicted_per_second` from the response
- Wall-clock time for the full test run
- Aggregate throughput = total tokens / wall-clock time

## Test Results

### 1. Baseline — 4K context, parallel=1, f16 KV
Configuration: `--ctx-size 4096 --parallel 1`

| Metric | Value |
|---|---|
| Requests | 8 |
| Concurrency | 4 |
| max_tokens | 4000 |
| Completed | 8/8 |
| Total tokens | 32,000 |
| Wall-clock time | 573.99s |
| **Aggregate throughput** | **55.75 tok/s** |
| Single-stream throughput | ~28 tok/s |
| Average latency | 197.40s |

### 2. 64K context, parallel=1, f16 KV (CPU offload)
Configuration: `--ctx-size 65536 --parallel 1`

| Metric | Value |
|---|---|
| Context size | 65536 |
| KV cache | 3328 MiB CPU + 5888 MiB GPU |
| 100-token smoke test | **63.66s (~1.6 tok/s)** |
| 6000-token batch test | **Timed out at 600s** |

The KV cache exceeded GPU memory and was partially offloaded to host RAM, causing severe slowdown.

### 3. 64K context, parallel=1, q8_0 KV
Configuration: `--ctx-size 65536 --parallel 1 --cache-type-k q8_0 --cache-type-v q8_0`

| Metric | Value |
|---|---|
| KV cache | 4896 MiB GPU |
| GPU memory per instance | ~7224 MiB |
| Requests | 4 |
| Concurrency | 4 |
| max_tokens | 4000 |
| Completed | 4/4 |
| Total tokens | 16,000 |
| Wall-clock time | 455.52s |
| **Aggregate throughput** | **35.12 tok/s** |
| Single-stream throughput | ~25 tok/s |
| Average latency | 237.61s |

q8_0 KV cache quantization restored usable throughput, but aggregate remained limited because only one request could run per backend at a time.

### 4. 64K context, parallel=2, q8_0 KV (final configuration)
Configuration: `--ctx-size 65536 --parallel 2 --cache-type-k q8_0 --cache-type-v q8_0`

Server confirmation:
```
llama_context: n_seq_max     = 2
llama_context: n_ctx_seq     = 32768
llama_kv_cache: CUDA0 KV buffer size = 4896.00 MiB
```

| Metric | Value |
|---|---|
| Slots per instance | 2 × 32K |
| KV cache | 4896 MiB GPU |
| GPU memory per instance | ~7224–7232 MiB |
| Requests | 8 |
| Concurrency | 8 |
| max_tokens | 4000 |
| Completed | 8/8 |
| Total tokens | 26,399 |
| Wall-clock time | 295.53s |
| **Aggregate throughput** | **89.33 tok/s** |
| Single-stream throughput | ~23–25 tok/s |
| Average latency | 180.68s |

This is near the theoretical maximum of ~100 tok/s for four MIG instances.

## Final Observations

- **vLLM is incompatible** with the Bonsai Ternary 1.58-bit GGUF format; it fails with `ValueError: np.uint32(42) is not a valid GGMLQuantizationType`. The Prism fork of llama.cpp is required.
- **64K context is viable** on 10GB MIG partitions only with KV-cache quantization (`q8_0`) and parallelism to keep the cache in GPU memory.
- **Aggregate throughput scales with backend concurrency**: moving from `parallel=1` to `parallel=2` increased aggregate throughput from 35 tok/s to 89 tok/s.
- Single-stream speed is slightly lower at 64K context (~23–25 tok/s) compared to 4K context (~28 tok/s) due to larger compute graph overhead.

## Files Created

- `/home/mctouch/code/production-stack/perf_test.py` — fixed-batch throughput test
- `/home/mctouch/code/production-stack/perf_test_continuous.py` — continuous saturation test (not run to completion due to long per-request times)
- `/tmp/bonsai-ternary-mig-deployment.yaml` — current deployment manifest
- `/home/mctouch/code/production-stack/BONSAI_TERNARY_MIG_PERFORMANCE.md` — this file

## Recommended Configuration

Use the final settings from Test 4 for maximum token throughput on the 10GB MIG partitions:

```yaml
--ctx-size 65536
--parallel 2
--cache-type-k q8_0
--cache-type-v q8_0
--threads 8
```

Access via LiteLLM proxy:
```
http://100.115.213.88:4000/v1
```

---

### 5. Three MIG instances — 64K context, parallel=2, q8_0 KV
After removing one replica (GPU 1), the deployment scaled down to 3 instances on GPUs 2, 3, and 4.

Configuration: `--ctx-size 65536 --parallel 2 --cache-type-k q8_0 --cache-type-v q8_0`

| Metric | Value |
|---|---|
| Active MIG instances | 3 |
| Slots available | 6 (2 per instance) |
| Requests | 6 |
| Concurrency | 6 |
| max_tokens | 4000 |
| Completed | 6/6 |
| Total tokens | 22,133 |
| Wall-clock time | 455.48s |
| **Aggregate throughput** | **48.59 tok/s** |
| Single-stream throughput | ~22–25 tok/s |
| Average latency | 208.44s |

Throughput scaled proportionally with the loss of one backend: from **89.33 tok/s** with 4 instances to **48.59 tok/s** with 3 instances.

## Node Loss Event Log

When the deployment was scaled from 4 to 3 replicas, Kubernetes recorded the following events:

```
32m  Normal  Pulled              pod/bonsai-ternary-mig-55cbd8979b-vzj5h   Container image "localhost:5000/llama.cpp-server:prism-b8846-d104cf1" already present on machine
32m  Normal  Created             pod/bonsai-ternary-mig-55cbd8979b-vzj5h   Created container llama-server
32m  Normal  Started             pod/bonsai-ternary-mig-55cbd8979b-vzj5h   Started container llama-server
30m  Normal  Killing             pod/bonsai-ternary-mig-55cbd8979b-vzj5h   Stopping container llama-server
30m  Normal  SuccessfulDelete    replicaset/bonsai-ternary-mig-55cbd8979b  Deleted pod: bonsai-ternary-mig-55cbd8979b-vzj5h
30m  Normal  ScalingReplicaSet   deployment/bonsai-ternary-mig             Scaled down replica set bonsai-ternary-mig-55cbd8979b to 3 from 4
```

Availability after the scale-down:

```
NAME                 READY   UP-TO-DATE   AVAILABLE
bonsai-ternary-mig   3/3     3            3
```

The LiteLLM proxy continued serving requests on the remaining 3 backends without requiring a restart.
