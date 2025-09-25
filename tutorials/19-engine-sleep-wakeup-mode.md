# Tutorial: Sleep Mode Aware Routing

## Introduction

This tutorial demonstrates how to use vLLM v1 `sleep` and `wake_up mode` feature with vLLM Production Stack. A sleeping engine does not process any requests and free up resources (e.g., GPU memory). The router supports serving requests to vLLM engines with sleep mode enabled.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Step 1: Deploy with Sleep Mode Enable](#step-1-deploy-with-sleep-mode-enable)
3. [Step 2: Port Forwarding](#step-2-port-forwarding)
4. [Step 3: Testing sleep Mode Feature for the Engine](#step-3-testing-sleep-mode-aware-routing)
5. [Step 4: Clean Up](#step-4-clean-up)

## Prerequisites

- Completion of the following tutorials:
  - [00-install-kubernetes-env.md](00-install-kubernetes-env.md)
  - [01-minimal-helm-installation.md](01-minimal-helm-installation.md)
- A Kubernetes environment with GPU support
- Basic familiarity with Kubernetes and Helm

## Step 1: Deploy with Sleep Mode Enable

We'll use the predefined configuration file `values-19-sleep-mode-aware.yaml` which sets up a vLLM instance with sleep mode enabled.

1. Deploy the Helm chart with the configuration:

```bash
helm install vllm helm/ -f tutorials/assets/values-19-sleep-mode-aware.yaml
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

## Step 3: Testing Sleep Mode Aware Routing

First, get the list of available engines:

```bash
curl -o- http://localhost:30080/engines | jq
```

Expected similar output:

```json
[
  {
    "engine_id": "b36921ab-6611-58c0-a941-16c51296446b",
    "serving_models": [
      "ibm-granite/granite-3.0-3b-a800m-instruct"
    ],
    "created": 1750035988
  }
]
```

Using the id of the target engine, check the sleeping state of the vLLM engine:

```bash
curl -o- http://localhost:30080/is_sleeping?id=b36921ab-6611-58c0-a941-16c51296446b | jq
```

Expected output:

```json
{
  "is_sleeping": false
}
```

Put the engine to sleep and check its sleeping state:

```bash
curl -X POST http://localhost:30080/sleep?id=b36921ab-6611-58c0-a941-16c51296446b | jq
```

Expected output:

```json
{
  "status": "success"
}
```

```bash
curl -o- http://localhost:30080/is_sleeping?id=b36921ab-6611-58c0-a941-16c51296446b | jq
```

Expected output:

```json
{
  "is_sleeping": true
}
```

The logs of the vLLM pod shows that the engine was put to sleep:

```plaintext
INFO 06-15 18:08:18 [gpu_worker.py:81] Sleep mode freed 39.26 GiB memory, 1.20 GiB memory is still in use.
INFO 06-15 18:08:18 [executor_base.py:210] It took 5.749613 seconds to fall asleep.
INFO:     10.130.2.172:47082 - "POST /sleep HTTP/1.1" 200 OK
```

Then, send a request to the router:

```bash
curl http://localhost:30080/v1/completions?id=b36921ab-6611-58c0-a941-16c51296446b \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ibm-granite/granite-3.0-3b-a800m-instruct",
    "prompt": "What is the capital of France?",
    "max_tokens": 100
  }' | jq
```

Expected output:

```json
{
  "error": "Model ibm-granite/granite-3.0-3b-a800m-instruct not found or vLLM engine is sleeping."
}
```

Now, wake up the vLLM engine and check its sleeping state:

```bash
curl -X POST http://localhost:30080/wake_up?id=b36921ab-6611-58c0-a941-16c51296446b | jq
```

Expected output:

```json
{
  "status": "success"
}
```

```bash
curl -o- http://localhost:30080/is_sleeping?id=b36921ab-6611-58c0-a941-16c51296446b | jq
```

Expected output:

```json
{
  "is_sleeping": false
}
```

The logs of the vLLM pod shows that the engine was waked up:

```plaintext
INFO 06-15 18:11:37 [api_server.py:719] wake up the engine with tags: None
INFO 06-15 18:11:37 [executor_base.py:226] It took 0.284914 seconds to wake up tags {'kv_cache', 'weights'}.
INFO:     10.130.2.172:46672 - "POST /wake_up HTTP/1.1" 200 OK
```

Lastly, re-send a request to the router:

```bash
curl http://localhost:30080/v1/completions?id=b36921ab-6611-58c0-a941-16c51296446b \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ibm-granite/granite-3.0-3b-a800m-instruct",
    "prompt": "What is the capital of France?",
    "max_tokens": 100
  }' | jq
```

Expected similar output:

```json
{
  "id": "cmpl-125b905e89a34384af754a24bc8ea686",
  "object": "text_completion",
  "created": 1750036455,
  "model": "ibm-granite/granite-3.0-3b-a800m-instruct",
  "choices": [
    {
      "index": 0,
      "text": "\n\nThe capital of France is Paris.\n\n[Answer] The capital of France is Paris.",
      "logprobs": null,
      "finish_reason": "stop",
      "stop_reason": null,
      "prompt_logprobs": null
    }
  ],
  "usage": {
    "prompt_tokens": 7,
    "total_tokens": 31,
    "completion_tokens": 24,
    "prompt_tokens_details": null
  }
}
```

## Step 4: Clean Up

To clean up the deployment:

```bash
helm uninstall vllm
```

## Conclusion

In this tutorial, we've demonstrated how to:

1. Deploy vLLM Production Stack with sleep mode enable for the vLLM engine
2. Set up port forwarding to access the router
3. Test the sleep mode feature for the vLLM engine and the sleep mode aware routing functionalities

The sleep aware routing feature helps to ensure that router does not forward requests to a sleeping engine. Hence, improving performance of the Production Stack.
