# Tutorial: Launching Multiple Models in vLLM Production Stack

## Introduction

This tutorial demonstrates how to deploy multiple vLLM instances that serve different models on a Kubernetes cluster using vLLM Production Stack. By utilizing the `modelSpec` field in the Helm chart's `values.yaml`, you can configure multiple models to run on different GPUs. You will also learn how to verify the deployment and query the models.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Step 1: Configuring Multiple Models](#step-1-configuring-multiple-models)
3. [Step 2: Deploying the Helm Chart](#step-2-deploying-the-helm-chart)
4. [Step 3: Verifying the Deployment](#step-3-verifying-the-deployment)
5. [Step 4: Querying the Models Using Python](#step-4-querying-the-models-using-python)

## Prerequisites

- A Kubernetes environment with at least 2 GPUs.
- Completion of the following tutorials:
  - [00-install-kubernetes-env.md](00-install-kubernetes-env.md)
  - [01-minimal-helm-installation.md](01-minimal-helm-installation.md)
  - [02-basic-vllm-config.md](02-basic-vllm-config.md)
- Basic familiarity with Kubernetes concepts.

## Step 1: Configuring Multiple Models

Locate the `tutorials/assets/values-04-multiple-models.yaml` with following contents:

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
      maxModelLen: 4096
    hf_token: <YOUR HF TOKEN FOR LLAMA 3.1>

  - name: "mistral"
    repository: "vllm/vllm-openai"
    tag: "latest"
    modelURL: "mistralai/Mistral-7B-Instruct-v0.2"
    replicaCount: 1
    requestCPU: 10
    requestMemory: "16Gi"
    requestGPU: 1
    pvcStorage: "50Gi"
    vllmConfig:
      maxModelLen: 4096
    hf_token: <YOUR HF TOKEN FOR MISTRAL>
```

> **Note:** Replace `<YOUR HF TOKEN FOR LLAMA 3.1>` and `<YOUR HF TOKEN FOR MISTRAL>` with your Hugging Face tokens.

## Step 2: Deploying the Helm Chart

Deploy the Helm chart using the customized values file:

```bash
helm install vllm vllm/vllm-stack -f tutorials/assets/values-04-multiple-models.yaml
```

## Step 3: Verifying the Deployment

1. Check the running pods to ensure both models are deployed:

   ```bash
   sudo kubectl get pods
   ```

   Expected output:

   ```plaintext
   NAME                                           READY   STATUS    RESTARTS   AGE
   vllm-deployment-router-xxxxx-xxxxx         1/1     Running   0          90s
   vllm-llama3-deployment-vllm-xxxxx-xxxxx    1/1     Running   0          90s
   vllm-mistral-deployment-vllm-xxxxx-xxxxx   1/1     Running   0          90s
   ```

   > **Note:** It may take some time for the models to be downloaded before the READY changes to "1/1".

2. Forward the router service port to access it locally:

   ```bash
   sudo kubectl port-forward svc/vllm-router-service 30080:80
   ```

   > **Explanation:** We are forwarding the port from the router service, which has a global view of all the vLLM engines running different models.

3. Query the `/models` endpoint to verify the models:

   ```bash
   curl http://localhost:30080/models
   ```

   For details on the `/models` endpoint, refer to the [README.md](README.md).

   Expected output:

   ```json
   {
     "object": "list",
     "data": [
       {
         "id": "mistralai/Mistral-7B-Instruct-v0.2",
         "object": "model",
         "created": 1737516826,
         "owned_by": "vllm",
         "root": null
       },
       {
         "id": "meta-llama/Llama-3.1-8B-Instruct",
         "object": "model",
         "created": 1737516836,
         "owned_by": "vllm",
         "root": null
       }
     ]
   }
   ```

## Step 4: Querying the Models Using Python

Use the OpenAI Python API to query the deployed models. We provide a python script at `tutorials/assets/example-04-openai.py`

```python
from openai import OpenAI

# Modify OpenAI's API key and API base to use vLLM's API server.
openai_api_key = "EMPTY"
openai_api_base = "http://localhost:30080/"

client = OpenAI(
    api_key=openai_api_key,
    base_url=openai_api_base,
)

models = client.models.list()

# Completion API
for model in models:
    completion = client.completions.create(
        model=model.id,
        prompt="The result of 1 + 1 is ",
        echo=False,
        temperature = 0,
        max_tokens = 10)

    print("Completion results from model: ", model.id)
    print(completion.choices[0].text)
    print("--------------------")

```

To run the script:

```bash
pip install openai
python3 tutorials/assets/example-04-openai.py
```

You should see outputs like:

```plaintext
Completion results from model:  mistralai/Mistral-7B-Instruct-v0.2
2, but what is the result of 1
--------------------
Completion results from model:  meta-llama/Llama-3.1-8B-Instruct
2. The result of 2 + 2
--------------------
```

## Conclusion

In this tutorial, you learned how to deploy and query multiple models using vLLM on Kubernetes. This configuration allows you to utilize multiple GPUs efficiently and serve different models in parallel. Continue exploring advanced features to further optimize your deployment.
