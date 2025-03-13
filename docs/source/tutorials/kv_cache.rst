.. tutorial_kv_cache:

KV Cache Offloading
===================

Introduction
------------

This tutorial demonstrates how to enable KV cache offloading using LMCache in a vLLM deployment. KV cache offloading moves large KV caches from GPU memory to CPU or disk, enabling more potential KV cache hits. vLLM Production Stack uses LMCache for KV cache offloading.

Prerequisites
-------------

* Installation of minimal example shown in :ref:`examples`
* Kubernetes environment with GPU support

Steps to follow
---------------

1. Configuring KV Cache Offloading
++++++++++++++++++++++++++++++++++

Locate the file ``tutorials/assets/values-05-cpu-offloading.yaml`` with the following content:

.. code-block:: yaml

    servingEngineSpec:
        modelSpec:
        - name: "mistral"
            repository: "lmcache/vllm-openai"
            tag: "latest"
            modelURL: "mistralai/Mistral-7B-Instruct-v0.2"
            replicaCount: 1
            requestCPU: 10
            requestMemory: "40Gi"
            requestGPU: 1
            pvcStorage: "50Gi"
            vllmConfig:
            enableChunkedPrefill: false
            enablePrefixCaching: false
            maxModelLen: 16384

            lmcacheConfig:
            enabled: true
            cpuOffloadingBufferSize: "20"

            hf_token: <YOUR HF TOKEN>

.. note::

    Note: Replace <YOUR HF TOKEN> with your actual Hugging Face token.

.. note::

    The ``lmcacheConfig`` field enables LMCache and sets the CPU offloading buffer size to ``20GB``. You can adjust this value based on your workload.

Step 2: Deploy the Stack
++++++++++++++++++++++++

Deploy the Helm chart using the predefined configuration file:

.. code-block:: bash

    helm install vllm vllm/vllm-stack -f tutorials/assets/values-05-cpu-offloading.yaml


Step 3: Validate Installation
++++++++++++++++++++++++++++++

3.1 Check the pod logs to verify LMCache is active:
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    sudo kubectl get pods


Identify the pod name for the vLLM deployment (e.g., ``vllm-mistral-deployment-vllm-xxxx-xxxx``). Then run:

.. code-block:: bash

    sudo kubectl logs -f <pod-name>


Look for the following log message to confirm LMCache is active:

.. code-block:: console

    INFO 01-21 20:16:58 lmcache_connector.py:41] Initializing LMCacheConfig under kv_transfer_config kv_connector='LMCacheConnector' kv_buffer_device='cuda' kv_buffer_size=1000000000.0 kv_role='kv_both' kv_rank=None kv_parallel_size=1 kv_ip='127.0.0.1' kv_port=14579
    INFO LMCache: Creating LMCacheEngine instance vllm-instance [2025-01-21 20:16:58,732] -- /usr/local/lib/python3.12/dist-packages/lmcache/experimental/cache_engine.py:237


2. Forward the router service port to access the stack locally:
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    sudo kubectl port-forward svc/vllm-router-service 30080:80


3. Send a request to the stack and observe the logs:
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    curl -X POST http://localhost:30080/completions \
        -H "Content-Type: application/json" \
        -d '{
            "model": "mistralai/Mistral-7B-Instruct-v0.2",
            "prompt": "Explain the significance of KV cache in language models.",
            "max_tokens": 10
        }'

Expected output:

The response from the stack should contain the completion result, and the logs should show LMCache activity, for example:

.. code-block:: console

    DEBUG LMCache: Store skips 0 tokens and then stores 13 tokens [2025-01-21 20:23:45,113] -- /usr/local/lib/python3.12/dist-packages/lmcache/integration/vllm/vllm_adapter.py:490
