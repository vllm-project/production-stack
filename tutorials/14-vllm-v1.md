# Tutorial: Running vLLM with v1 Configuration

## Introduction

This tutorial demonstrates how to deploy vLLM with v1 configuration enabled. The v1 configuration uses the LMCacheConnectorV1 for KV cache management, which provides improved performance and stability for certain workloads.

## Prerequisites

- A Kubernetes cluster with GPU support
- Helm installed on your local machine
- Completion of the following tutorials:
  - [00-install-kubernetes-env.md](00-install-kubernetes-env.md)
  - [01-minimal-helm-installation.md](01-minimal-helm-installation.md)

## Step 1: Understanding the Configuration

The configuration file `values-14-vllm-v1.yaml` includes several important settings:

1. Model Configuration:
   - Using Llama-3.1-8B-Instruct model
   - Single replica deployment
   - Resource requirements: 6 CPU, 16Gi memory, 1 GPU
   - 50Gi persistent storage

2. vLLM Configuration:
   - v1 mode enabled (v1: 1)
   - bfloat16 precision
   - Maximum sequence length of 4096 tokens
   - GPU memory utilization set to 80%

3. LMCache Configuration:
   - KV cache offloading enabled
   - 20GB CPU offloading buffer size

4. Cache Server Configuration:
   - Single replica cache server
   - Naive serialization/deserialization
   - Resource limits: 2 CPU, 10Gi memory

Feel freet to change the above parameters for your own scenario.

## Step 2: Deploying the Stack

1. First, ensure you're in the correct directory:

   ```bash
   cd production-stack
   ```

2. Deploy the stack using Helm:

   ```bash
   helm install vllm helm/ -f tutorials/assets/values-14-vllm-v1.yaml
   ```

3. Verify the deployment:

   ```bash
   kubectl get pods
   ```

   You should see:
   - A vLLM pod for the Llama model
   - A cache server pod

## Step 3: Verifying the Configuration

1. Check the vLLM pod logs to verify v1 configuration:

   ```bash
   kubectl logs -f <vllm-pod-name>
   ```

   Look for the following log message:

   ```log
   INFO 04-29 12:12:25 [factory.py:64] Creating v1 connector with name: LMCacheConnectorV1
   ```

2. Forward the router service port:

   ```bash
   kubectl port-forward svc/vllm-router-service 30080:80
   ```

## Step 4: Testing the Deployment

Send a test request to verify the deployment:

```bash
curl -X POST http://localhost:30080/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "meta-llama/Llama-3.1-8B-Instruct",
    "prompt": "Explain the benefits of using v1 configuration in vLLM.",
    "max_tokens": 100
  }'
```

Note that you need to send a prompt greater than 256 tokens in order to reuse the KV cache (the chunk size set in LMCache)

## Conclusion

This tutorial demonstrated how to deploy vLLM with v1 configuration enabled. The v1 configuration provides improved KV cache management through LMCacheConnectorV1, which can lead to better performance for certain workloads. You can adjust the configuration parameters in the values file to optimize for your specific use case.
