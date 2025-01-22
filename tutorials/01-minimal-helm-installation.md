# Tutorial: Minimal Setup of the LLMStack

## Introduction
This tutorial guides you through a minimal setup of the LLMStack using one vLLM instance with the `facebook/opt-125m` model. By the end of this tutorial, you will have a working deployment of vLLM on a Kubernetes environment with GPU.

## Table of Contents
- [Introduction](#introduction)
- [Table of Contents](#table-of-contents)
- [Prerequisites](#prerequisites)
- [Steps](#steps)
  - [1. Deploy vLLM Instance](#1-deploy-vllm-instance)
  - [2. Validate Installation](#2-validate-installation)
  - [3. Send a Query to the Stack](#3-send-a-query-to-the-stack)
    - [3.1. Forward the Service Port](#31-forward-the-service-port)
    - [3.2. Query the OpenAI-Compatible API](#32-query-the-openai-compatible-api)
    - [3.3. Query the OpenAI Completion Endpoint](#33-query-the-openai-completion-endpoint)
  - [4. Uninstall](#4-uninstall)

## Prerequisites
1. A Kubernetes environment with GPU support. If not set up, follow the [00-install-kubernetes-env](00-install-kubernetes-env.md) guide.
2. Helm installed. Refer to the [install-helm.sh](install-helm.sh) script for instructions.
3. kubectl installed. Refer to the [install-kubectl.sh](install-kubectl.sh) script for instructions.
4. vLLM project repository cloned: [LLMStack repository](https://github.com/vllm-project/production-stack).
5. Basic familiarity with Kubernetes and Helm.

## Steps

### 1. Deploy vLLM Instance

#### Step 1.1: Use Predefined Configuration
The LLMStack repository provides a predefined configuration file, `values-minimal-example.yaml`, located at `tutorials/assets/values-minimal-example.yaml`. This file contains the following content:

```yaml
servingEngineSpec:
  modelSpec:
  - name: "opt125m"
    repository: "lmcache/vllm-openai"
    tag: "latest"
    modelURL: "facebook/opt-125m"

    replicaCount: 1

    requestCPU: 6
    requestMemory: "16Gi"
    requestGPU: 1

    pvcStorage: "10Gi"
```

Explanation of the key fields:
- **`modelSpec`**: Defines the model configuration, including:
  - `name`: A name for the model deployment.
  - `repository`: Docker repository hosting the model image.
  - `tag`: Docker image tag.
  - `modelURL`: Specifies the LLM model to use.
- **`replicaCount`**: Sets the number of replicas to deploy.
- **`requestCPU` and `requestMemory`**: Specifies the CPU and memory resource requests for the pod.
- **`requestGPU`**: Specifies the number of GPUs required.
- **`pvcStorage`**: Allocates persistent storage for the model.

#### Step 1.2: Deploy the Helm Chart
Deploy the Helm chart using the predefined configuration file:
```bash
sudo helm repo add llmstack-repo https://lmcache.github.io/helm/
sudo helm install llmstack llmstack-repo/vllm-stack -f tutorials/assets/values-minimal-example.yaml
```
Explanation of the command:
- `llmstack-repo`: The Helm repository for the LLMStack.
- `llmstack`: The name of the Helm release.
- `-f tutorials/assets/values-minimal-example.yaml`: Specifies the predefined configuration file.

### 2. Validate Installation

#### Step 2.1: Monitor Deployment Status
Monitor the deployment status using:
```bash
sudo kubectl get pods
```
Expected output:
- Pods for the `llmstack` deployment should transition to the `Running` state.
```
NAME                                               READY   STATUS    RESTARTS   AGE
llmstack-deployment-router-859d8fb668-2x2b7        1/1     Running   0          2m38s
llmstack-opt125m-deployment-vllm-84dfc9bd7-vb9bs   1/1     Running   0          2m38s
```
_Note_: It may take some time for the containers to download the Docker images and LLM weights.

### 3. Send a Query to the Stack

#### Step 3.1: Forward the Service Port
Expose the `llmstack-router-service` port to the host machine:
```bash
sudo kubectl port-forward svc/llmstack-router-service 30080:80
```

#### Step 3.2: Query the OpenAI-Compatible API to list the available models
Test the stack's OpenAI-compatible API by querying the available models:
```bash
curl -o- http://localhost:30080/models
```
Expected output:
```json
{
  "object": "list",
  "data": [
    {
      "id": "facebook/opt-125m",
      "object": "model",
      "created": 1737428424,
      "owned_by": "vllm",
      "root": null
    }
  ]
}
```

#### Step 3.3: Query the OpenAI Completion Endpoint
Send a query to the OpenAI `/completion` endpoint to generate a completion for a prompt:
```bash
curl -X POST http://localhost:30080/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "facebook/opt-125m",
    "prompt": "Once upon a time,",
    "max_tokens": 10
  }'
```
Expected output:
```json
{
  "id": "completion-id",
  "object": "text_completion",
  "created": 1737428424,
  "model": "facebook/opt-125m",
  "choices": [
    {
      "text": " there was a brave knight who...",
      "index": 0,
      "finish_reason": "length"
    }
  ]
}
```
This demonstrates the model generating a continuation for the provided prompt.

### 4. Uninstall

To remove the deployment, run:
```bash
sudo helm uninstall llmstack
```
