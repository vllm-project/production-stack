# Tutorial: Multi-Round QA Benchmark (Multi-GPU)

## Introduction

This tutorial provides a step-by-step guide to setting up and running benchmarks for comparing vLLM Production Stack, Naive Kubernetes, and AIBrix, with multi-round QA benchmark on 8 A100 GPUs (``gpu_8x_a100_80gb_sxm4
``) from Lambda Labs.

## Table of Contents

- [Tutorial: Multi-Round QA Benchmark (Multi-GPU)](#tutorial-multi-round-qa-benchmark-multi-gpu)
  - [Introduction](#introduction)
  - [Table of Contents](#table-of-contents)
  - [Prerequisites](#prerequisites)
  - [Step 1: Running Benchmarks with vLLM Production Stack](#step-1-running-benchmarks-with-vllm-production-stack)
  - [Step 2: Running Benchmarks with Naive Kubernetes](#step-2-running-benchmarks-with-naive-kubernetes)
  - [Step 3: Running Benchmarks with AIBrix](#step-3-running-benchmarks-with-aibrix)
  - [Conclusion](#conclusion)

## Prerequisites

- Completion of the following tutorials:
  - [00-install-kubernetes-env.md](00-install-kubernetes-env.md)
  - [01-minimal-helm-installation.md](01-minimal-helm-installation.md)
- In `benchmarks/multi-round-qa/`, Install necessary python packages needed to run multi-round QA benchmark script by `pip install -r requirements.txt`.
- Hardware requirements:
  - GPU: this tutorial requires **8 GPUs** to run.
  - CPU: this tutorial requires **at least 1.2T of CPU memory** for allocating the CPU buffer size.

## Step 1: Running Benchmarks with vLLM Production Stack

First, start a vLLM Production Stack server.

To begin with, create a `stack.yaml` configuration file as follows (and please **replace** ``<YOUR_HUGGINGFACE_TOKEN>`` with your own huggingface token):

```yaml
servingEngineSpec:
  runtimeClassName: ""
  modelSpec:
  - name: "llama3"
    repository: "lmcache/vllm-openai"
    tag: "latest"
    modelURL: "meta-llama/Llama-3.1-8B-Instruct"
    replicaCount: 8
    requestCPU: 10
    requestMemory: "150Gi"
    requestGPU: 1
    pvcStorage: "50Gi"
    pvcAccessMode:
      - ReadWriteOnce
    vllmConfig:
      enableChunkedPrefill: false
      enablePrefixCaching: false
      maxModelLen: 32000
      dtype: "bfloat16"
      extraArgs: ["--disable-log-requests", "--swap-space", 0]
    lmcacheConfig:
      enabled: true
      cpuOffloadingBufferSize: "120"
    hf_token: <YOUR_HUGGINGFACE_TOKEN>

routerSpec:
  resources:
  requests:
    cpu: "2"
    memory: "8G"
  limits:
    cpu: "2"
    memory: "8G"
  routingLogic: "session"
  sessionKey: "x-user-id"
```

Deploy the vLLM Production Stack server by:

```bash
sudo helm repo add vllm https://vllm-project.github.io/production-stack
sudo helm install vllm vllm/vllm-stack -f stack.yaml
```

Then you can verify the pod readiness:

```bash
kubectl get pods
```

Once the pods are ready, run the port forwarding:

```bash
sudo kubectl port-forward svc/vllm-router-service 30080:80
```

Finally, run the benchmarking code by:

```bash
bash warmup.sh meta-llama/Llama-3.1-8B-Instruct http://localhost:30080/v1/
bash run.sh meta-llama/Llama-3.1-8B-Instruct http://localhost:30080/v1/ stack
```

## Step 2: Running Benchmarks with Naive Kubernetes

First, start a naive Kubernetes server.

To begin with, create a `naive.yaml` configuration file (and please **replace** ``<YOUR_HUGGINGFACE_TOKEN>`` with your own huggingface token):

```yaml
servingEngineSpec:
  runtimeClassName: ""
  modelSpec:
  - name: "llama3"
    repository: "vllm/vllm-openai"
    tag: "latest"
    modelURL: "meta-llama/Llama-3.1-8B-Instruct"
    replicaCount: 8
    requestCPU: 10
    requestMemory: "150Gi"
    requestGPU: 1
    pvcStorage: "50Gi"
    pvcMatchLabels:
      model: "llama3"
    pvcAccessMode:
      - ReadWriteOnce
    vllmConfig:
      enableChunkedPrefill: false
      enablePrefixCaching: true
      maxModelLen: 32000
      extraArgs: ["--disable-log-requests", "--swap-space", 0]

    lmcacheConfig:
      enabled: false

    hf_token: <YOUR HUGGINGFACE TOKEN>

routerSpec:
  resources:
  requests:
    cpu: "2"
    memory: "8G"
  limits:
    cpu: "2"
    memory: "8G"
  routingLogic: "roundrobin"
```

Deploy the Naive K8s stack server:

```bash
sudo helm repo add vllm https://vllm-project.github.io/production-stack
sudo helm install vllm vllm/vllm-stack -f naive.yaml
```

Then you can verify the pod readiness:

```bash
kubectl get pods
```

Once the pods are ready, run the port forwarding:

```bash
sudo kubectl port-forward svc/vllm-router-service 30080:80
```

Finally, run the benchmarking code by:

```bash
bash warmup.sh meta-llama/Llama-3.1-8B-Instruct http://localhost:30080/v1/
bash run.sh meta-llama/Llama-3.1-8B-Instruct http://localhost:30080/v1/ native
```

## Step 3: Running Benchmarks with AIBrix

We followed the installation steps documented in [AIBrix's official repo](https://aibrix.readthedocs.io/latest/getting_started/installation/lambda.html) to install their necessary packages needed to run on the Lambda server.

To align the configurations used in benchmarking vLLM Production Stack and naive K8s, we changed the configurations documented in [AIBrix's official repo](https://aibrix.readthedocs.io/latest/features/distributed-kv-cache.html) to enable AIBrix's KV Cache CPU offloading.
Specifically, we changed the model name in their [deployment configuration yaml file](https://aibrix.readthedocs.io/latest/features/distributed-kv-cache.html) at lines #4, #6, #17, #21, #38, #81, #86 and #99 from `deepseek-coder-7b-instruct` to `llama3-1-8b`; and line #36 from `deepseek-ai/deepseek-coder-6.7b-instruct` to `meta-llama/Llama-3.1-8B-Instruct`; and line #57 from and line #73 from `deepseek-coder-7b-kvcache-rpc:9600` to `llama3-1-8b-kvcache-rpc:9600` `/var/run/vineyard-kubernetes/default/deepseek-coder-7b-kvcache` to `/var/run/vineyard-kubernetes/default/llama3-1-8b-kvcache`.
We changed max model len at line #40 from `8000` to `24000`.
We also changed the CPU offload memory limit at line #47 from `10` to `120` to match the configuration used in [Step 1](#step-1-running-benchmarks-with-vllm-production-stack).
Finally, we changed the replica number at line #9 from `1` to `8`.

We also changed the CPU memory limit in AIBrix's KV cache server config: At line #4, we changed from `deepseek-coder-7b-kvcache` to `llama3-1-8b-kvcache`; and at line #7, we changed from `deepseek-coder-7b-instruct` to `llama3-1-8b`; and at line #17, we changed from `4Gi` to `150Gi` for aligning with the configuration used in [Step 1](#step-1-running-benchmarks-with-vllm-production-stack).

Finally, we follow the steps in [AIBrix's official repo](https://aibrix.readthedocs.io/latest/getting_started/installation/lambda.html) to start AIBrix server and then run the benchmarking code by:

```bash
bash warmup.sh llama3-1-8b http://localhost:8888/v1/
bash run.sh llama3-1-8b http://localhost:8888/v1/ aibrix
```

## Conclusion

This tutorial provides a comprehensive guide to setting up and benchmarking vLLM Production Stack, Native Kubernetes, and AIBrix. By following these steps, you can effectively evaluate their performance in your environment.
