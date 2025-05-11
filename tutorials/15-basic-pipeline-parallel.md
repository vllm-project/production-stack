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

- **`raySpec`**: Required when using KubeRay to enable pipeline parallelism.
- **`headNode`**: Specifies the resource requirements for the Kuberay head node and must be defined accordingly.
- **`name`**: The unique identifier for your model deployment.
- **`repository`**: The Docker repository containing the model's serving engine image.
- **`tag`**: Specifies the version of the model image to use.
- **`modelURL`**: The URL pointing to the model on Hugging Face or another hosting service.
- **`replicaCount`**: The number of replicas for each Kuberay worker pod.
- **`requestCPU`**: The amount of CPU resources requested per Kuberay worker pod.
- **`requestMemory`**: Memory allocation for each Kuberay worker pod; sufficient memory is required to load the model.
- **`requestGPU`**: Specifies the number of GPUs to allocate for each Kuberay worker pod.
- **`vllmConfig`**: Contains model-specific configurations:
  - `tensorParallelSize`: Defines the number of GPUs allocated to each worker pod.
  - `pipelineParallelSize`: Specifies the degree of pipeline parallelism. `The total number of GPUs` used is calculated as `pipelineParallelSize × tensorParallelSize`.
- **`shmSize`**: Configures the shared memory size to ensure adequate memory is available for inter-process communication during tensor and pipeline parallelism execution.
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

   - The vllm-deployment-router pod functions as the request router, directing incoming traffic to the appropriate model-serving pod.

   - The vllm-distilgpt2-raycluster-head pod is responsible for running the primary vLLM command.

   - The vllm-distilgpt2-raycluster-ray-worker-* pods serve the model and handle inference requests.

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

   To verify that the service is operational, execute the following commands:

   ```bash
   kubectl port-forward svc/vllm-router-service 30080:80
   curl http://localhost:30080/v1/models
   ```

   **Note:** Port forwarding must be performed from a separate shell session. If the deployment is configured correctly, you should receive a response similar to the following:

   ```plaintext
   {"object":"list","data":[{"id":"distilbert/distilgpt2","object":"model","created":1746978162,"owned_by":"vllm","root":null}]}
   ```

   You may also perform a basic inference test to validate that pipeline parallelism is functioning as expected. Use the following curl command:

   ```bash
   curl -X POST http://localhost:30080/v1/completions \
    -H "Content-Type: application/json" \
    -d '{
      "model": "distilbert/distilgpt2",
      "prompt": "Once upon a time,",
      "max_tokens": 10
    }'
   ```

   A successful response should resemble the following output:

   ```plaintext
   {"id":"cmpl-27e058ce9f0443dd96b76aced16f8b90","object":"text_completion","created":1746978495,"model":"distilbert/distilgpt2","choices":[{"index":0,"text":" the dim of light lingered as it projected enough","logprobs":null,"finish_reason":"length","stop_reason":null,"prompt_logprobs":null}],"usage":{"prompt_tokens":5,"total_tokens":15,"completion_tokens":10,"prompt_tokens_details":null}}
   ```

Please refer to Step 3 in the [01-minimal-helm-installation](01-minimal-helm-installation.md) tutorial for querying the deployed vLLM service.

## Conclusion

In this tutorial, you configured and deployed the vLLM serving engine with support for pipeline parallelism across multiple GPUs within a Kubernetes environment using KubeRay. Additionally, you learned how to verify the deployment and monitor the associated pods to ensure proper operation. For further customization and configuration options, please consult the `values.yaml` file and the Helm chart documentation.
