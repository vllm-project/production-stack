# Offload KV Cache to CPU RAM and Local Disk with LMCache

This tutorial demonstrates how to enable KV cache offloading using LMCache in a vLLM deployment. KV cache offloading moves large KV caches from GPU memory to CPU or disk, enabling more potential KV cache hits.
vLLM Production Stack uses LMCache for KV cache offloading. For more details, see the [LMCache GitHub repository](https://github.com/LMCache/LMCache).

## Installing Prerequisites

Before running this setup, ensure you have:

1. GCP CLI installed and configured with credential and region set up [[Link]](https://cloud.google.com/sdk/docs/install)
2. Kubectl
3. Helm
4. Quota of GPU

## TLDR

Disclaimer: This script requires cloud resources and will incur costs. Please make sure all resources are shut down properly.

Set the environment variables. Check that they meet the minimum requirements for your LLM model. Default values will be used for any unset variables. In this example, we use an A3 mega machine type to run the meta-llama/Llama-3.3-70B-Instruct model and use local SSD as the local disk backend through Kubernetes ephemeral storage(emptyDir).

```bash
export CLUSTER_NAME="my-vllm-cluster"
export CLUSTER_VERSION="1.32.3-gke.1440000"
export ZONE="us-central1-c"
export ACCELERATOR_TYPE="nvidia-h100-mega-80gb"
```

To run the service, go to "deployment_on_cloud/gcp" and run:

```bash
 bash entry_point_basic.sh ../../tutorials/assets/gke-example/values-01-offload-kv-cache-local-disk.yaml
```

> **Note:** Replace `<YOUR HF TOKEN>` with your actual Hugging Face token.

Check the pod logs to verify LMCache is active:

   ```bash
   kubectl get pods
   ```

  Pods for the vllm deployment should transition to Ready and the Running state. It will take some time for the Pod to be READY since the model we use in this example is large.

  Expected output:

  ```plaintext
  NAME                                            READY   STATUS    RESTARTS   AGE
  vllm-deployment-router-6786bdcc5b-flj2x        1/1     Running   0          12m
  vllm-llama3-deployment-vllm-7dd564bc8f-7mf5x   1/1     Running   0          12m
  ```

   Identify the pod name for the vLLM deployment (e.g., `vllm-llama3-deployment-vllm-xxxx-xxxx`). Then run:

   ```bash
   kubectl logs -f <pod-name>
   ```

   Look for entries in the log indicating LMCache is enabled and operational. An example output is:

   ```plaintext
   INFO 09-04 01:05:32 [factory.py:50] Creating v1 connector with name: LMCacheConnectorV1 and engine_id: d5ba9e99-fc24-4622-973a-45fbd86a2567
   ```

Get the router service EXTERNAL-IP:

   ```bash
   kubectl get service vllm-router-service
   ```

Expected output:

```plaintext
NAME                  TYPE           CLUSTER-IP      EXTERNAL-IP      PORT(S)                       AGE
vllm-router-service   LoadBalancer   34.118.227.38   35.188.143.203   80:31588/TCP,9000:31522/TCP   18h
```

Send a request to the stack and observe the logs:

   ```bash
   export EXTERNAL_IP="35.188.143.203"

   curl -X POST http://${EXTERNAL_IP}:80/v1/completions \
     -H "Content-Type: application/json" \
     -d '{
       "model": "meta-llama/Llama-3.3-70B-Instruct",
       "prompt": "Explain the significance of KV cache in language models.",
       "max_tokens": 10
     }'
   ```

Expected output:

The response from the stack should contain the completion result, and the logs should show LMCache activity, for example:

```plaintext
(EngineCore_0 pid=328) [2025-09-04 00:14:16,137] LMCache INFO: Reqid: cmpl-a8448bb936e242b29f82bde1a3dccc36-0, Total tokens 12, LMCache hit tokens: 0, need to load: 0 (vllm_v1_adapter.py:1034:lmcache.integration.vllm.vllm_v1_adapter)
```

Clean up the service with:

```bash
bash clean_up_basic.sh $CLUSTER_NAME
```

For step by step explanation, see (./02-GPU-GKE-deployment.md## Step by Step Explanation)

## Summary

This tutorial covers:

✅ Creating a GKE cluster for vLLM deployment with LMCache cpu RAM and local disk offloading enabled.

✅ Deploying the vLLM application using Helm.

✅ Cleaning up resources after deployment.

Now your GCP GKE production stack is ready for large-scale AI model deployment! 🚀
