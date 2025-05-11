# Tutorial: Basic vLLM Configurations

## Introduction

This tutorial guides you through the basic configurations required to deploy a vLLM serving engine in a Kubernetes environment with distributed inference support using Kuberay. You will learn how to launch the vLLM serving engine with pipeline parallelism.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Step 1: Preparing the Configuration File](#step-1-preparing-the-configuration-file)
3. [Step 2: Applying the Configuration](#step-2-applying-the-configuration)
4. [Step 3: Verifying the Ray Cluster](#step-3-verifying-the-deployment)

## Prerequisites

- A Kubernetes environment with GPU support, as set up in the [00-install-kubernetes-env tutorial](00-install-kubernetes-env.md).
- Install kuberay operator on the Kubernetes environment with [00-install-kubernetes-env tutorial](00-install-kubernetes-env.md).
- Helm installed on your system.
- Access to a HuggingFace token (`HF_TOKEN`).

## Step 1: Preparing the Configuration File

1. Locate the example configuration file [`tutorials/assets/values-15-minimal-pipeline-parallel-example.yaml`](assets/values-15-minimal-pipeline-parallel-example.yaml).
2. Open the file and update the following fields:
    - Write your actual huggingface token in `hf_token: <YOUR HF TOKEN>` in the yaml file.

### Explanation of Key Items in `values-15-minimal-pipeline-parallel-example.yaml`

- **`name`**: The unique identifier for your model deployment.
- **`repository`**: The Docker repository containing the model's serving engine image.
- **`tag`**: Specifies the version of the model image to use.
- **`modelURL`**: The URL pointing to the model on Hugging Face or another hosting service.
- **`replicaCount`**: The number of replicas for each Kuberay worker pod.
- **`requestCPU`**: The amount of CPU resources requested per Kuberay worker pod.
- **`requestMemory`**: Memory allocation for each Kuberay worker pod; sufficient memory is required to load the model.
- **`requestGPU`**: Specifies the number of GPUs to allocate for each Kuberay worker pod.
- **`vllmConfig`**: Contains model-specific configurations:
  - `tensorParallelSize`: Number of GPUs to assign for each worker pod.
  - `pipelineParallelSize`: Pipeline parallel factor. `Total GPUs` = `pipelineParallelSize` x `tensorParallelSize`
- **`shmSize`**: Shared memory size to enable appropriate shared memory across multiple processes used to run tensor and pipeline parallelism.
- **`hf_token`**: The Hugging Face token for authenticating with the Hugging Face model hub.

### Example Snippet

```yaml
servingEngineSpec:
  runtimeClassName: ""
  raySpec:
    headNode:
      requestCPU: 2
      requestMemory: "20Gi"
  modelSpec:
  - name: "distilgpt2"
    repository: "vllm/vllm-openai"
    tag: "latest"
    modelURL: "distilbert/distilgpt2"

    replicaCount: 2

    requestCPU: 2
    requestMemory: "20Gi"
    requestGPU: 1

    vllmConfig:
      tensorParallelSize: 1
      pipelineParallelSize: 2

    shmSize: "20Gi"

    hf_token: <YOUR HF TOKEN>
```

## Step 2: Applying the Configuration

Deploy the configuration using Helm:

```bash
helm repo add vllm https://vllm-project.github.io/production-stack
helm install vllm vllm/vllm-stack -f tutorials/assets/values-15-minimal-pipeline-parallel-example.yaml
```

Expected output:

You should see output indicating the successful deployment of the Helm chart:

```plaintext
NAME: vllm
LAST DEPLOYED: Sun May 11 15:10:34 2025
NAMESPACE: default
STATUS: deployed
REVISION: 1
TEST SUITE: None
```

## Step 3: Verifying the Deployment

1. Check the status of the pods:

   ```bash
   kubectl get pods
   ```

   Expected output:

   You should see the following pods:

   ```plaintext
   NAME                                          READY   STATUS    RESTARTS   AGE
   kuberay-operator-975995b7d-75jqd              1/1     Running   0          24h
   vllm-deployment-router-8666bf6464-ds8pm       1/1     Running   0          40s
   vllm-distilgpt2-raycluster-head-74qvn         1/1     Running   0          40s
   vllm-distilgpt2-raycluster-ray-worker-jlgj8   1/1     Running   0          40s
   vllm-distilgpt2-raycluster-ray-worker-jrcrl   1/1     Running   0          40s
   ```

   - The `vllm-deployment-router` pod acts as the router, managing requests and routing them to the appropriate model-serving pod.
   - The `vllm-distilgpt2-raycluster-head` pod runs actual vllm command.
   - `vllm-distilgpt2-raycluster-ray-worker-*` pods serves the actual model for inference.

2. Verify the service is exposed correctly:

   ```bash
   kubectl get services
   ```

   Expected output:

   Ensure there are services for both the serving engine and the router:

   ```plaintext
   NAME                                  TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)             AGE
   kuberay-operator                      ClusterIP   10.99.122.176   <none>        8080/TCP            24h
   kubernetes                            ClusterIP   10.96.0.1       <none>        443/TCP             5d1h
   vllm-distilgpt2-engine-service        ClusterIP   10.105.193.58   <none>        80/TCP              2m42s
   vllm-distilgpt2-raycluster-head-svc   ClusterIP   None            <none>        8000/TCP,8080/TCP   2m42s
   vllm-router-service                   ClusterIP   10.108.70.18    <none>        80/TCP              2m42s
   ```

   - The `vllm-engine-service` exposes the serving engine.
   - The `vllm-router-service` handles routing and load balancing across model-serving pods.

3. Test the health endpoint:

   ```bash
   curl http://<SERVICE_IP>/health
   ```

   Replace `<SERVICE_IP>` with the external IP of the service. If everything is configured correctly, you will get:

   ```plaintext
   {"status":"healthy"}
   ```

Please refer to Step 3 in the [01-minimal-helm-installation](01-minimal-helm-installation.md) tutorial for querying the deployed vLLM service.

## Step 4 (Optional): Multi-GPU Deployment

So far, you have configured and deployment vLLM serving engine with a single GPU. You may also deploy a serving engine on multiple GPUs with the following example configuration snippet:

```yaml
servingEngineSpec:
  runtimeClassName: ""
  modelSpec:
  - name: "llama3"
    repository: "vllm/vllm-openai"
    tag: "latest"
    modelURL: "meta-llama/Llama-3.1-8B-Instruct"
    replicaCount: 1
    requestCPU: 10
    requestMemory: "16Gi"
    requestGPU: 2
    pvcStorage: "50Gi"
    pvcAccessMode:
      - ReadWriteOnce
    vllmConfig:
      enableChunkedPrefill: false
      enablePrefixCaching: false
      maxModelLen: 4096
      tensorParallelSize: 2
      dtype: "bfloat16"
      extraArgs: ["--disable-log-requests", "--gpu-memory-utilization", "0.8"]
    hf_token: <YOUR HF TOKEN>
    shmSize: "20Gi"
```

Note that only tensor parallelism is supported for now. The field ``shmSize`` has to be configured if you are requesting ``requestGPU`` to be more than one, to enable appropriate shared memory across multiple processes used to run tensor parallelism.

## Conclusion

In this tutorial, you configured and deployed a vLLM serving engine with pipeline parallelism support (on multiple GPUs) in a Kubernetes environment with Kuberay. You also learned how to verify its deployment and pods and ensure it is running as expected. For further customization, refer to the `values.yaml` file and Helm chart documentation.
