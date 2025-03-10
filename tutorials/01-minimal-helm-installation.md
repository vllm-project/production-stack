# Tutorial: Minimal Setup of the vLLM Production Stack

## Introduction

This tutorial guides you through a minimal setup of the vLLM Production Stack using one vLLM instance with the `facebook/opt-125m` model. By the end of this tutorial, you will have a working deployment of vLLM on a Kubernetes environment with GPU.

## Table of Contents

- [Tutorial: Minimal Setup of the vLLM Production Stack](#tutorial-minimal-setup-of-the-vllm-production-stack)
  - [Introduction](#introduction)
  - [Table of Contents](#table-of-contents)
  - [Prerequisites](#prerequisites)
  - [Steps](#steps)
    - [1. Deploy vLLM Instance](#1-deploy-vllm-instance)
      - [1.1: Use Predefined Configuration](#11-use-predefined-configuration)
      - [1.2: Deploy the Helm Chart](#12-deploy-the-helm-chart)
    - [2. Validate Installation](#2-validate-installation)
      - [2.1: Monitor Deployment Status](#21-monitor-deployment-status)
    - [3. Send a Query to the Stack](#3-send-a-query-to-the-stack)
      - [3.1: Forward the Service Port](#31-forward-the-service-port)
      - [3.2: Query the OpenAI-Compatible API to list the available models](#32-query-the-openai-compatible-api-to-list-the-available-models)
      - [3.3: Query the OpenAI Completion Endpoint](#33-query-the-openai-completion-endpoint)
    - [4. Uninstall](#4-uninstall)

## Prerequisites

1. A Kubernetes environment with GPU support. If not set up, follow the [00-install-kubernetes-env](00-install-kubernetes-env.md) guide.
2. Helm installed. Refer to the [install-helm.sh](install-helm.sh) script for instructions.
3. kubectl installed. Refer to the [install-kubectl.sh](install-kubectl.sh) script for instructions.
4. the project repository cloned: [vLLM Production Stack repository](https://github.com/vllm-project/production-stack).
5. Basic familiarity with Kubernetes and Helm.

## Steps

### 1. Deploy vLLM Instance

#### 1.1: Use Predefined Configuration

The vLLM Production Stack repository provides a predefined configuration file, `values-01-minimal-example.yaml`, located at `tutorials/assets/values-01-minimal-example.yaml`. This file contains the following content:

```yaml
servingEngineSpec:
  runtimeClassName: ""
  modelSpec:
  - name: "opt125m"
    repository: "vllm/vllm-openai"
    tag: "latest"
    modelURL: "facebook/opt-125m"

    replicaCount: 1

    requestCPU: 6
    requestMemory: "16Gi"
    requestGPU: 1
    # Optional resource limits - if not specified, only GPU will have a limit
    # limitCPU: "8"
    # limitMemory: "32Gi"

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

**Note:** If you intend to set up TWO vllm pods, please refer to `tutorials/assets/values-01-2pods-minimal-example.yaml`.

#### 1.2: Deploy the Helm Chart

Deploy the Helm chart using the predefined configuration file:

```bash
sudo helm repo add vllm https://vllm-project.github.io/production-stack
sudo helm install vllm vllm/vllm-stack -f tutorials/assets/values-01-minimal-example.yaml
```

Explanation of the command:

- `vllm` in the first command: The Helm repository.
- `vllm` in the second command: The name of the Helm release.
- `-f tutorials/assets/values-01-minimal-example.yaml`: Specifies the predefined configuration file.

### 2. Validate Installation

#### 2.1: Monitor Deployment Status

Monitor the deployment status using:

```bash
sudo kubectl get pods
```

Expected output:

- Pods for the `vllm` deployment should transition to `Ready` and the `Running` state.

```plaintext
NAME                                               READY   STATUS    RESTARTS   AGE
vllm-deployment-router-859d8fb668-2x2b7        1/1     Running   0          2m38s
vllm-opt125m-deployment-vllm-84dfc9bd7-vb9bs   1/1     Running   0          2m38s
```

_Note_: It may take some time for the containers to download the Docker images and LLM weights.

### 3. Send a Query to the Stack

#### 3.1: Forward the Service Port

Expose the `vllm-router-service` port to the host machine:

```bash
sudo kubectl port-forward svc/vllm-router-service 30080:80
```

#### 3.2: Query the OpenAI-Compatible API to list the available models

Test the stack's OpenAI-compatible API by querying the available models:

```bash
curl -o- http://localhost:30080/v1/models
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

#### 3.3: Query the OpenAI Completion Endpoint

Send a query to the OpenAI `/completion` endpoint to generate a completion for a prompt:

```bash
curl -X POST http://localhost:30080/v1/completions \
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
sudo helm uninstall vllm
```
