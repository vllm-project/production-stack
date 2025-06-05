.. _tutorial_disagg:

Disaggregated Prefill
=====================

Introduction
------------------------

This tutorial explains how to run the disaggregated prefill system, which splits the model execution into prefill and decode phases across different servers. This approach can improve throughput and resource utilization by separating the initial processing (prefill) from the token generation (decode) phases.

Prerequisites
-------------------------

* Docker installed with NVIDIA runtime support
* NVIDIA GPUs available (at least 2 GPUs recommended)
* Python 3.12 installed
* Hugging Face token with access to Llama models
* vLLM and its dependencies installed

Local Deployment
---------------------------

Step 1: Start the Prefill Server
++++++++++++++++++++++++++++++++++

The prefill server handles the initial processing of the input sequence. This server runs on GPU 0 and uses port 8100.

.. code-block:: bash

    bash examples/disaggregated_prefill/start_prefill.sh

This script starts a Docker container with the following key configurations:

* Uses GPU 0 (``CUDA_VISIBLE_DEVICES=0``)
* Runs on port 8100
* Acts as a NIXL sender
* Uses the Llama-3.1-8B-Instruct model
* Configured as a KV producer and a Nixl sender

Step 2: Start the Decode Server
++++++++++++++++++++++++++++++++++

The decode server handles the generation of new tokens. This server runs on GPU 1 and uses port 8200.

.. code-block:: bash

    bash examples/disaggregated_prefill/start_decode.sh

This script starts a Docker container with the following key configurations:

* Uses GPU 1 (``CUDA_VISIBLE_DEVICES=1``)
* Runs on port 8200
* Acts as a NIXL receiver
* Uses the Llama-3.1-8B-Instruct model
* Configured as a KV consumer and a nixl receiver

Step 3: Start the Router
++++++++++++++++++++++++++++++++++

The router coordinates between the prefill and decode servers, handling request routing.

.. code-block:: bash

    python3 -m vllm_router.app --port 8005 \
        --service-discovery static \
        --static-backends "http://localhost:8100,http://localhost:8200" \
        --static-models "meta-llama/Llama-3.1-8B-Instruct,meta-llama/Llama-3.1-8B-Instruct" \
        --static-model-labels "llama-prefill,llama-decode" \
        --log-stats \
        --log-stats-interval 10 \
        --engine-stats-interval 10 \
        --request-stats-window 10 \
        --routing-logic disaggregated_prefill \
        --prefill-model-labels "llama-prefill" \
        --decode-model-labels "llama-decode"

Key router configurations:

* Runs on port 8005
* Uses static service discovery
* Implements disaggregated prefill routing logic
* Logs statistics every 10 seconds
* Routes requests based on model labels

Step 4: Submit Requests
++++++++++++++++++++++++++++++++++

Once all servers are running, you can submit requests to the router at ``localhost:8005``. Here's an example curl request:

.. code-block:: bash

    curl http://localhost:8005/v1/completions \
        -H "Content-Type: application/json" \
        -d '{
            "model": "meta-llama/Llama-3.1-8B-Instruct",
            "prompt": "Your prompt here",
            "max_tokens": 100
        }'

You should see logs from LMCache like the following on the decoder instance's side:

.. code-block:: console

    [2025-05-26 20:12:21,913] LMCache DEBUG: Scheduled to load 5 tokens for request cmpl-058cf35e022a479f849a60daefbade9e-0 (vllm_v1_adapter.py:299:lmcache.integration.vllm.vllm_v1_adapter)
    [2025-05-26 20:12:21,915] LMCache DEBUG: Retrieved 6 out of 6 out of total 6 tokens (cache_engine.py:330:lmcache.experimental.cache_engine)

Kubernetes Deployment
-------------------------------

For production environments, you can deploy the disaggregated prefill system using Kubernetes and Helm. This approach provides better scalability, resource management, and high availability.

Step 1: Create Configuration File
++++++++++++++++++++++++++++++++++

Create a configuration file ``values-16-disagg-prefill.yaml`` with the following content:

.. code-block:: yaml

    # Unified configuration for disaggregated prefill setup
    # Unified configuration for disaggregated prefill setup
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
            gpuMemoryUtilization: 0.6
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
          hf_token: <your-hf-token>
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
          hf_token: <your-hf-token>
          labels:
            model: "llama-decode"
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

    helm install pd helm/ -f tutorials/assets/values-16-disagg-prefill.yaml

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

    kubectl port-forward svc/pd-router-service 30080:80

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
