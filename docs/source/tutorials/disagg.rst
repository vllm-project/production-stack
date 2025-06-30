.. _tutorial_disagg:

Disaggregated Prefill
=====================

Introduction
------------------------

This tutorial explains how to run the disaggregated prefill system, which splits the model execution into prefill and decode phases across different servers. This approach can improve throughput and resource utilization by separating the initial processing (prefill) from the token generation (decode) phases.

Prerequisites
-------------------------

* A Kubernetes cluster with GPU support and NVLink enabled
* NVIDIA GPUs available (at least 2 GPUs recommended)
* ``kubectl`` configured to talk to your cluster
* Helm installed and initialized locally
* Completion of the following setup tutorials:

  * `00-install-kubernetes-env.md <https://github.com/vllm-project/production-stack/blob/main/tutorials/00-a-install-multinode-kubernetes-env.md>`__
  * `01-minimal-helm-installation.md <https://github.com/vllm-project/production-stack/blob/main/tutorials/01-b-minimal-helm-installation.md>`__

Kubernetes Deployment
-------------------------------

For production environments, you can deploy the disaggregated prefill system using Kubernetes and Helm. This approach provides better scalability, resource management, and high availability.

Step 1: Create Configuration File
++++++++++++++++++++++++++++++++++

Create a configuration file ``values-16-disagg-prefill.yaml`` with the following content:

.. code-block:: yaml

  servingEngineSpec:
    enableEngine: true
    runtimeClassName: ""
    containerPort: 8000
    modelSpec:
      # Prefill node configuration
      - name: "llama-prefill"
        repository: "lmcache/vllm-openai"
        tag: "2025-05-27-v1"
        modelURL: "meta-llama/Llama-3.1-8B-Instruct"
        replicaCount: 1
        requestCPU: 8
        requestMemory: "30Gi"
        # requestGPU: 1
        pvcStorage: "50Gi"
        vllmConfig:
          enablePrefixCaching: true
          maxModelLen: 32000
          v1: 1
        lmcacheConfig:
          cudaVisibleDevices: "0"
          enabled: true
          kvRole: "kv_producer"
          enableNixl: true
          nixlRole: "sender"
          nixlPeerHost: "vllm-llama-decode-engine-service"
          nixlPeerPort: "55555"
          nixlBufferSize: "1073741824"  # 1GB
          nixlBufferDevice: "cuda"
          nixlEnableGc: true
          enablePD: true
          cpuOffloadingBufferSize: 0
        hf_token: <hf-token>
        labels:
          model: "llama-prefill"
      # Decode node configuration
      - name: "llama-decode"
        repository: "lmcache/vllm-openai"
        tag: "2025-05-27-v1"
        modelURL: "meta-llama/Llama-3.1-8B-Instruct"
        replicaCount: 1
        requestCPU: 8
        requestMemory: "30Gi"
        # requestGPU: 1
        pvcStorage: "50Gi"
        vllmConfig:
          enablePrefixCaching: true
          maxModelLen: 32000
          v1: 1
        lmcacheConfig:
          cudaVisibleDevices: "1"
          enabled: true
          kvRole: "kv_consumer"  # Set decode node as consumer
          enableNixl: true
          nixlRole: "receiver"
          nixlPeerHost: "0.0.0.0"
          nixlPeerPort: "55555"
          nixlBufferSize: "1073741824"  # 1GB
          nixlBufferDevice: "cuda"
          nixlEnableGc: true
          enablePD: true
        hf_token: <hf-token>
        labels:
          model: "llama-decode"
    containerSecurityContext:
      capabilities:
        add:
          - SYS_PTRACE
  routerSpec:
    enableRouter: true
    repository: "lmcache/lmstack-router"
    tag: "pd"
    replicaCount: 1
    containerPort: 8000
    servicePort: 80
    routingLogic: "disaggregated_prefill"
    engineScrapeInterval: 15
    requestStatsWindow: 60
    enablePD: true
    resources:
      requests:
        cpu: "4"
        memory: "16G"
      limits:
        cpu: "4"
        memory: "32G"
    labels:
      environment: "router"
      release: "router"
    extraArgs:
      - "--prefill-model-labels"
      - "llama-prefill"
      - "--decode-model-labels"
      - "llama-decode"


Step 2: Deploy Using Helm
++++++++++++++++++++++++++++++++++

Install the deployment using Helm with the configuration file:

.. code-block:: bash

    helm install vllm helm/ -f tutorials/assets/values-16-disagg-prefill.yaml

This will deploy:

* A prefill server with the specified configuration
* A decode server with the specified configuration
* A router to coordinate between them

The configuration includes:

* Resource requests and limits for each component
* NIXL communication settings for LMCache
* Model configurations
* Router settings for disaggregated prefill

Step 3: Verify Deployment
++++++++++++++++++++++++++++++++++

Check the status of your deployment:

.. code-block:: bash

    kubectl get pods
    kubectl get services

You should see pods for:

* The prefill server
* The decode server
* The router

Step 4: Access the Service
++++++++++++++++++++++++++++++++++

First do port forwarding to access the service:

.. code-block:: bash

    kubectl port-forward svc/vllm-router-service 30080:80

And then send a request to the router by:

.. code-block:: bash

    curl http://localhost:30080/v1/completions \
        -H "Content-Type: application/json" \
        -d '{
            "model": "meta-llama/Llama-3.1-8B-Instruct",
            "prompt": "Your prompt here",
            "max_tokens": 100
        }'

You should see logs from LMCache like the following on the decoder instance's side:

.. code-block:: console

    [2025-05-26 20:12:21,913] LMCache DEBUG: Scheduled to load 6 tokens for request cmpl-058cf35e022a479f849a60daefbade9e-0 (vllm_v1_adapter.py:299:lmcache.integration.vllm.vllm_v1_adapter)
    [2025-05-26 20:12:21,915] LMCache DEBUG: Retrieved 6 out of 6 out of total 6 tokens (cache_engine.py:330:lmcache.experimental.cache_engine)
