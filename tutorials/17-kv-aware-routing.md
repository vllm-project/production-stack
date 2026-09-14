# Tutorial: KV Cache Aware Routing

## Introduction

This tutorial demonstrates how to use KV cache aware routing in the vLLM Production Stack. KV cache aware routing ensures that subsequent requests with the same prompt prefix are routed to the same instance, maximizing KV cache utilization and improving performance.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Step 1: Deploy with KV Cache Aware Routing](#step-1-deploy-with-kv-cache-aware-routing)
3. [Step 2: Port Forwarding](#step-2-port-forwarding)
4. [Step 3: Testing KV Cache Aware Routing](#step-3-testing-kv-cache-aware-routing)
5. [Step 4: Clean Up](#step-4-clean-up)

## Prerequisites

- Completion of the following tutorials:
  - [00-install-kubernetes-env.md](00-install-kubernetes-env.md)
  - [01-minimal-helm-installation.md](01-minimal-helm-installation.md)
- A Kubernetes environment with GPU support
- Basic familiarity with Kubernetes and Helm

## Step 1: Deploy with KV Cache Aware Routing

We'll use the predefined configuration file `values-17-kv-aware.yaml` which sets up two vLLM instances with KV cache aware routing enabled.

1. Deploy the Helm chart with the configuration:

```bash
helm install vllm helm/ -f tutorials/assets/values-17-kv-aware.yaml
```

Note that to add more instances, you need to specify different ``instanceId`` in ``lmcacheConfig``.

Wait for the deployment to complete:

```bash
kubectl get pods -w
```

## Step 2: Port Forwarding

Forward the router service port to your local machine:

```bash
kubectl port-forward svc/vllm-router-service 30080:80
```

## Step 3: Testing KV Cache Aware Routing

First, send a request to the router:

```bash
curl http://localhost:30080/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/gpt-oss-20b",
    "prompt": "What is the capital of France?",
    "max_tokens": 100
  }'
```

Then, send another request with the same prompt prefix:

```bash
curl http://localhost:30080/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/gpt-oss-20b",
    "prompt": "What is the capital of France? And what is its population?",
    "max_tokens": 100
  }'
```

You should observe that the second request is routed to the same instance as the first request. This is because the KV cache aware router detects that the second request shares a prefix with the first request and routes it to the same instance to maximize KV cache utilization.

## Step 4: Clean Up

To clean up the deployment:

```bash
helm uninstall vllm
```

## Troubleshooting: the silent-miss preconditions

KV-aware routing fails **silently**: when any precondition below is violated,
requests still succeed - the router just falls back to session/QPS placement
and every KV lookup misses. If routing never reports cache hits, check these
in order (each was hit in a real deployment):

1. **Same lmcache version on router and engines.** The controller<->worker
   ZMQ messages are not a stable protocol across lmcache versions - an old
   controller rejects a newer worker's `RegisterMsg` as an unknown message
   type, the worker never registers, and every lookup misses. The router
   image and engine images must carry the same lmcache.
2. **The router needs the engines' vLLM installed.** KV chunk hashes are
   rooted in vLLM's `NONE_HASH` and hash function. A router without vLLM
   falls back to `NONE_HASH=0` and a plain Python hash - a different hash
   chain from the engines', so no lookup can ever match. This is why
   `docker/Dockerfile.kvaware` builds the router FROM a vLLM image.
3. **Set `PYTHONHASHSEED` identically on router and engines** when the
   builtin hash is in use - Python's `hash()` is seed-randomized per
   process, and unseeded processes can never agree on chunk hashes.
   (lmcache logs a warning about this at startup; it is easy to miss.)
4. **Worker heartbeats must be enabled** (`lmcacheConfig.workerHeartbeatTime`
   in this tutorial's values, mapping to
   `LMCACHE_LMCACHE_WORKER_HEARTBEAT_TIME`; the chart consumes the key via a
   `hasKey` guard in `helm/templates/deployment-vllm-multi.yaml`, so it does
   not appear in `values.yaml` defaults). lmcache workers default to
   never sending heartbeats while the controller reaps silent workers after
   ~30 seconds - with the default, the KV index silently empties shortly
   after startup and hits stop "for no reason". Hand-rolled engine configs
   must set this explicitly.
5. **One cache-owning instance per IP.** The controller attributes
   instances to endpoints by IP alone (`QueryInstMsg`), so several engines
   sharing one IP (e.g. one multi-GPU host with host networking) are
   indistinguishable and requests kv-followed to the unmapped ones fall
   back (older routers crashed with a 500 - see the fix in the router
   changelog). Give each engine a distinct routable IP.
6. **Sliding-window / hybrid-attention models pay a hidden KV cost.**
   `LMCacheConnectorV1` does not support vLLM's hybrid KV cache manager,
   so configuring it makes vLLM silently disable that manager - on models
   with sliding-window layers (Gemma-family and others) this inflates
   per-token KV usage several-fold, shrinking the effective KV budget by
   as much as ~10x. Only a startup log line warns about it. lmcache's
   `LMCacheMPConnector` (multiprocess cache server) is the HMA-capable
   path for such models.

## Conclusion

In this tutorial, we've demonstrated how to:

1. Deploy vLLM Production Stack with KV cache aware routing
2. Set up port forwarding to access the router
3. Test the KV cache aware routing functionality

The KV cache aware routing feature helps improve performance by ensuring that requests with shared prefixes are routed to the same instance, maximizing KV cache utilization.
