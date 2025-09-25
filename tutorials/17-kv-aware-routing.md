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
    "model": "meta-llama/Llama-3.1-8B-Instruct",
    "prompt": "What is the capital of France?",
    "max_tokens": 100
  }'
```

Then, send another request with the same prompt prefix:

```bash
curl http://localhost:30080/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "meta-llama/Llama-3.1-8B-Instruct",
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

## Conclusion

In this tutorial, we've demonstrated how to:

1. Deploy vLLM Production Stack with KV cache aware routing
2. Set up port forwarding to access the router
3. Test the KV cache aware routing functionality

The KV cache aware routing feature helps improve performance by ensuring that requests with shared prefixes are routed to the same instance, maximizing KV cache utilization.
