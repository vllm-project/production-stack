# Tutorial: Priority-Based Routing

## Introduction

This tutorial demonstrates how to use priority-based routing in the vLLM Production Stack. Priority routing lets you mark individual requests as more important than others — via a request header or a body field — so that the router steers them to the least-loaded serving engine, and forwards the priority value to vLLM so its native priority scheduler can preempt lower-priority work within the engine. This is useful for tiered service levels (e.g. premium vs. free traffic), keeping interactive requests responsive under batch load, or protecting health/readiness probes when the cluster is busy.

Under the hood, `priority` is an integer where **lower means higher priority** (matching vLLM's own convention). Requests with a priority *strictly below* a configurable threshold are routed to the least-loaded engine; every other request round-robins across all engines, so no engine is ever reserved and left idle.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Step 1: Deploy with Priority Routing](#step-1-deploy-with-priority-routing)
3. [Step 2: Port Forwarding](#step-2-port-forwarding)
4. [Step 3: Testing Priority Routing](#step-3-testing-priority-routing)
5. [Step 4: Clean Up](#step-4-clean-up)

## Prerequisites

- Completion of the following tutorials:
  - [00-install-kubernetes-env.md](00-install-kubernetes-env.md)
  - [01-minimal-helm-installation.md](01-minimal-helm-installation.md)
- A Kubernetes environment with GPU support
- Basic familiarity with Kubernetes and Helm

## Step 1: Deploy with Priority Routing

We'll use the predefined configuration file `values-26-priority-routing.yaml`, which deploys two vLLM replicas and enables `routing-logic=priority` on the router. It also sets `--scheduling-policy priority` on the vLLM engines themselves — this is required for in-engine preemption to actually take effect; without it, vLLM simply ignores the injected `priority` field as a safe no-op.

The router-side flags are passed via `routerSpec.extraArgs`:

| Flag | Value in this tutorial | Meaning |
| --- | --- | --- |
| `--priority-header` | `x-request-priority` | Request header carrying the priority |
| `--priority-field` | `priority` | Request body field used if the header is absent |
| `--priority-default` | `0` | Priority assigned when neither header nor field is set |
| `--priority-threshold` | `0` | Requests with `priority < 0` are treated as high-priority |

1. Deploy the Helm chart with the configuration:

```bash
helm install vllm helm/ -f tutorials/assets/values-26-priority-routing.yaml
```

Wait for the deployment to complete:

```bash
kubectl get pods -w
```

## Step 2: Port Forwarding

Forward the router service port to your local machine:

```bash
kubectl port-forward svc/vllm-router-service 30080:80
```

In a second terminal, start tailing the router's logs so you can see its routing decisions as you send requests in the next step:

```bash
kubectl logs -f deployment/vllm-deployment-router -c router-container
```

## Step 3: Testing Priority Routing

First, send a few default-priority requests (no header set) to build up load on the engines:

```bash
for i in 1 2 3 4; do
  curl -s http://localhost:30080/v1/completions \
    -H "Content-Type: application/json" \
    -d '{
      "model": "meta-llama/Llama-3.2-1B-Instruct",
      "prompt": "Write a long story about a dragon.",
      "max_tokens": 200
    }' > /dev/null &
done
```

While those are still in flight, send a high-priority request using the `x-request-priority` header with a value below the threshold (`0`):

```bash
curl http://localhost:30080/v1/completions \
  -H "Content-Type: application/json" \
  -H "x-request-priority: -1" \
  -d '{
    "model": "meta-llama/Llama-3.2-1B-Instruct",
    "prompt": "What is the capital of France?",
    "max_tokens": 50
  }'
```

Check the router logs from Step 2. You should see the default-priority requests round-robin across both engine URLs, while the `-1`-priority request is routed to whichever engine currently has the least in-flight load:

```text
Routing request <id> with session id None to http://<engine-a-ip>:8000 ...
Routing request <id> with session id None to http://<engine-b-ip>:8000 ...
Routing request <id> with session id None to http://<engine-a-ip>:8000 ...
Routing request <id> with session id None to http://<engine-b-ip>:8000 ...
```

The high-priority request lands on whichever of the two showed the lower in-flight count at that moment. You can also send a request with the equivalent body field instead of the header (used only when the header is absent):

```bash
curl http://localhost:30080/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "meta-llama/Llama-3.2-1B-Instruct",
    "prompt": "What is the capital of France?",
    "max_tokens": 50,
    "priority": -1
  }'
```

Because `--scheduling-policy priority` is enabled on the engines, the forwarded `priority` field also lets vLLM preempt lower-priority requests that are already running, so the high-priority request's time-to-first-token isn't stuck behind the batch of default-priority requests you started earlier.

## Step 4: Clean Up

To clean up the deployment:

```bash
helm uninstall vllm
```

## Conclusion

In this tutorial, we've demonstrated how to:

1. Deploy vLLM Production Stack with priority routing enabled, including the matching `--scheduling-policy priority` engine flag
2. Configure the priority header, body field, default, and threshold via `routerSpec.extraArgs`
3. Send requests at different priority levels and confirm via the router logs that high-priority traffic is steered to the least-loaded engine while default-priority traffic round-robins

Priority routing gives operators a lever to guarantee preferential treatment for latency-sensitive or business-critical traffic without reserving any engine capacity when no high-priority traffic is present.
