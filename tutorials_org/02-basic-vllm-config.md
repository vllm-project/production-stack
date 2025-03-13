# Tutorial: Basic vLLM Configurations

## Introduction
This tutorial guides you through the basic configurations required to deploy a vLLM serving engine in a Kubernetes environment with GPU support. You will learn how to specify the model details, set up necessary environment variables (like `HF_TOKEN`), and launch the vLLM serving engine.

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Step 1: Preparing the Configuration File](#step-1-preparing-the-configuration-file)
3. [Step 2: Applying the Configuration](#step-2-applying-the-configuration)
4. [Step 3: Verifying the Deployment](#step-3-verifying-the-deployment)

## Prerequisites
- A Kubernetes environment with GPU support, as set up in the [00-install-kubernetes-env tutorial](00-install-kubernetes-env.md).
- Helm installed on your system.
- Access to a Hugging Face token (`HF_TOKEN`).

## Step 1: Preparing the Configuration File

1. Locate the example configuration file `tutorials/assets/values-02-basic-config.yaml`.
2. Open the file and update the following fields:
    - Replace `<USERS SHOULD PUT THEIR HF_TOKEN HERE>` with your actual Hugging Face token.

### Explanation of Key Items in `values-02-basic-config.yaml`

- **`name`**: The unique identifier for your model deployment.
- **`repository`**: The Docker repository containing the model's serving engine image.
- **`tag`**: Specifies the version of the model image to use.
- **`modelURL`**: The URL pointing to the model on Hugging Face or another hosting service.
- **`replicaCount`**: The number of replicas for the deployment, allowing scaling for load.
- **`requestCPU`**: The amount of CPU resources requested per replica.
- **`requestMemory`**: Memory allocation for the deployment; sufficient memory is required to load the model.
- **`requestGPU`**: Specifies the number of GPUs to allocate for the deployment.
- **`pvcStorage`**: Defines the Persistent Volume Claim size for model storage.
- **`vllmConfig`**: Contains model-specific configurations:
  - `enableChunkedPrefill`: Optimizes performance by prefetching model chunks.
  - `enablePrefixCaching`: Speeds up response times for common prefixes in queries.
  - `maxModelLen`: The maximum sequence length the model can handle.
  - `dtype`: Data type for computations, e.g., `bfloat16` for faster performance on modern GPUs.
  - `extraArgs`: Additional arguments passed to the vLLM engine for fine-tuning behavior.
- **`env`**: Environment variables such as `HF_TOKEN` for authentication with Hugging Face.

### Example Snippet
```yaml
servingEngineSpec:
  modelSpec:
  - name: "llama3"
    repository: "vllm/vllm-openai"
    tag: "latest"
    modelURL: "meta-llama/Llama-3.1-8B-Instruct"
    replicaCount: 1

    requestCPU: 10
    requestMemory: "16Gi"
    requestGPU: 1

    pvcStorage: "50Gi"

    vllmConfig:
      enableChunkedPrefill: false
      enablePrefixCaching: false
      maxModelLen: 16384
      dtype: "bfloat16"
      extraArgs: ["--disable-log-requests", "--gpu-memory-utilization", "0.8"]

    env:
      - name: HF_TOKEN
        value: <YOUR_HF_TOKEN>

```

## Step 2: Applying the Configuration

1. Deploy the configuration using Helm:

```bash
sudo helm repo add llmstack-repo https://lmcache.github.io/helm/
sudo helm install llmstack llmstack-repo/vllm-stack -f tutorials/assets/values-02-basic-config.yaml
```

### Expected Output
You should see output indicating the successful deployment of the Helm chart:

```plaintext
Release "llmstack" has been deployed. Happy Helming!
NAME: llmstack
LAST DEPLOYED: <timestamp>
NAMESPACE: default
STATUS: deployed
REVISION: 1
```

## Step 3: Verifying the Deployment

1. Check the status of the pods:

```bash
sudo kubectl get pods
```

### Expected Output
You should see the following pods:

```plaintext
NAME                                             READY   STATUS    RESTARTS   AGE
pod/llmstack-deployment-router-xxxx-xxxx         1/1     Running   0          3m23s
llmstack-llama3-deployment-vllm-xxxx-xxxx        1/1     Running   0          3m23s
```

- The `llmstack-deployment-router` pod acts as the router, managing requests and routing them to the appropriate model-serving pod.
- The `llmstack-llama3-deployment-vllm` pod serves the actual model for inference.

2. Verify the service is exposed correctly:

```bash
sudo kubectl get services
```

### Expected Output
Ensure there are services for both the serving engine and the router:

```plaintext
NAME                      TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)        AGE
llmstack-engine-service   ClusterIP   10.103.98.170    <none>        80/TCP    4m
llmstack-router-service   ClusterIP   10.103.110.107   <none>        80/TCP    4m
```

- The `llmstack-engine-service` exposes the serving engine.
- The `llmstack-router-service` handles routing and load balancing across model-serving pods.

3. Test the health endpoint:

```bash
curl http://<SERVICE_IP>/health
```

Replace `<SERVICE_IP>` with the external IP of the service. If everything is configured correctly, you will get:

```plaintext
{"status":"healthy"}
```

Please refer to Step 3 in the [01-minimal-helm-installation](01-minimal-helm-installation.md) tutorial for querying the deployed vLLM service.

## Conclusion
In this tutorial, you configured and deployed a vLLM serving engine with GPU support in a Kubernetes environment. You also learned how to verify its deployment and ensure it is running as expected. For further customization, refer to the `values.yaml` file and Helm chart documentation.

