# Disaggregated Prefill Orchestrated Mode

This example demonstrates the `disaggregated_prefill_orchestrated` routing mode, which orchestrates the prefill→decode flow internally within the router. Unlike the LMCache-based `disaggregated_prefill` mode, this approach uses vLLM's native `kv_transfer_params` for KV cache handoff.

## Overview

In this mode, the router:

1. Receives a client request
2. Sends the request to the **prefill endpoint** with `kv_transfer_params` and `max_tokens=1`
3. Extracts `kv_transfer_params` from the prefill response
4. Forwards the request with `kv_transfer_params` to the **decode endpoint**
5. Streams the decode response back to the client

This is designed for backends that support vLLM's native KV transfer interface (e.g., NxDI on AWS Trainium).

## Prerequisites

- Kubernetes cluster with appropriate accelerator nodes (e.g., AWS Trainium)
- vLLM backend with KV transfer support (e.g., via NxDI's nixl connector)
- Model artifacts and dependencies available on a shared PVC
- production-stack router with `disaggregated_prefill_orchestrated` routing logic

## Deployment

### 1. Deploy Prefill and Decode Pods

```bash
kubectl apply -f prefill-deploy.yaml
kubectl apply -f decode-deploy.yaml
```

Wait for pods to be ready:

```bash
kubectl get pods -w
```

### 2. Deploy the Router

```bash
kubectl apply -f router-deploy.yaml
```

### 3. Verify Deployment

```bash
kubectl get pods
```

Expected output:

```text
NAME                      READY   STATUS    RESTARTS   AGE
decode-xxx                1/1     Running   0          1m
prefill-xxx               1/1     Running   0          1m
router-xxx                1/1     Running   0          1m
```

## Testing

### Send a Request

Port-forward to the router:

```bash
kubectl port-forward deployment/router 8000:8000
```

Send a test request:

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama31-8b",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 200,
    "temperature": 0
  }'
```

### Expected Response

```json
{
  "id": "chatcmpl-xxx",
  "model": "llama31-8b",
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "Hello, how can I assist you today?"
    },
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 36,
    "completion_tokens": 10,
    "total_tokens": 46
  }
}
```

### Verify Orchestration in Router Logs

```bash
kubectl logs deployment/router
```

You should see logs like:

```text
[INFO] Starting orchestrated disaggregated inference
[INFO] Prefill endpoint: http://172.x.x.x:8000
[INFO] Decode endpoint: http://172.x.x.x:8000
[INFO] Sending prefill request to http://172.x.x.x:8000/v1/chat/completions
[INFO] Prefill completed in 0.08s (TTFT)
[DEBUG] Prefill response keys: dict_keys(['id', 'object', ..., 'kv_transfer_params'])
[INFO] Sending decode request to http://172.x.x.x:8000/v1/chat/completions
[INFO] Orchestrated request completed, total time = 0.87s
```

## Configuration Notes

### Router Configuration

Key router arguments for this mode:

- `--routing-logic=disaggregated_prefill_orchestrated` - Enables orchestrated mode
- `--service-discovery=k8s` - Uses Kubernetes pod discovery
- `--k8s-label-selector="app in (prefill,decode)"` - Discovers prefill/decode pods
- `--prefill-model-labels=prefill` - Label to identify prefill pods
- `--decode-model-labels=decode` - Label to identify decode pods

### Pod Labels

Prefill and decode pods must have appropriate labels for discovery:

- Prefill pods: `app: prefill`, `model: prefill`
- Decode pods: `app: decode`, `model: decode`

## Differences from `disaggregated_prefill` Mode

| Feature         | `disaggregated_prefill`  | `disaggregated_prefill_orchestrated` |
| --------------- | ------------------------ | ------------------------------------ |
| KV Transfer     | LMCache + NIXL           | vLLM native `kv_transfer_params`     |
| Client Requests | 2 (prefill, then decode) | 1 (router orchestrates)              |
| Router Role     | Transparent routing      | Orchestration                        |
| Backend         | LMCache-enabled vLLM     | Any vLLM with KV transfer support    |
