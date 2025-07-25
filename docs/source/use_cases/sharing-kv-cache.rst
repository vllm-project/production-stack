Sharing KV Cache Across Instances
==================================

This tutorial demonstrates how to enable remote KV cache storage using LMCache in a vLLM deployment. Remote KV cache sharing moves large KV caches from GPU memory to a remote shared storage, enabling more KV cache hits and potentially making the deployment more fault tolerant.

vLLM Production Stack uses LMCache for remote KV cache sharing. For more details, see the `LMCache GitHub repository <https://github.com/LMCache/LMCache>`_.

Table of Contents
-----------------

1. Prerequisites_
2. `Step 1: Configuring Remote KV Cache Storage`_
3. `Step 2: Deploying the Helm Chart`_
4. `Step 3: Verifying the Installation`_
5. `Benchmark the Performance Gain of Remote Shared Storage (Work in Progress)`_

Prerequisites
-------------

- Completion of the following tutorials:

  - :doc:`../getting_started/prerequisite`
  - :doc:`../getting_started/quickstart`
  - :doc:`../deployment/helm`

- A Kubernetes environment with GPU support.

Step 1: Configuring Remote KV Cache Storage
--------------------------------------------

Locate the file `tutorials/assets/values-06-remote-shared-storage.yaml <https://github.com/vllm-project/production-stack/blob/main/tutorials/assets/values-06-remote-shared-storage.yaml>`_ with the following content:

.. code-block:: yaml

   servingEngineSpec:
     runtimeClassName: ""
     modelSpec:
     - name: "mistral"
       repository: "lmcache/vllm-openai"
       tag: "latest"
       modelURL: "mistralai/Mistral-7B-Instruct-v0.2"
       replicaCount: 2
       requestCPU: 10
       requestMemory: "40Gi"
       requestGPU: 1
       pvcStorage: "50Gi"
       vllmConfig:
         enableChunkedPrefill: false
         enablePrefixCaching: false
         maxModelLen: 16384
         v1: 1

       lmcacheConfig:
         enabled: true
         cpuOffloadingBufferSize: "20"

       hf_token: <YOUR HF TOKEN>

   cacheserverSpec:
     replicaCount: 1
     containerPort: 8080
     servicePort: 81
     serde: "naive"

     repository: "lmcache/vllm-openai"
     tag: "latest"
     resources:
       requests:
         cpu: "4"
         memory: "8G"
       limits:
         cpu: "4"
         memory: "10G"

     labels:
       environment: "cacheserver"
       release: "cacheserver"

.. note::
   Replace ``<YOUR HF TOKEN>`` with your actual Hugging Face token.

Also, right now ``v1`` has to be set to ``1`` to use LMCache docker image with ``latest`` tag.

The ``CacheserverSpec`` starts a remote shared KV cache storage.

Step 2: Deploying the Helm Chart
---------------------------------

Deploy the Helm chart using the customized values file:

.. code-block:: bash

   helm install vllm vllm/vllm-stack -f tutorials/assets/values-06-shared-storage.yaml

Step 3: Verifying the Installation
-----------------------------------

1. Check the pod logs to verify LMCache is active:

   .. code-block:: bash

      kubectl get pods

   Identify the pod name for the vLLM deployment (e.g., ``vllm-mistral-deployment-vllm-xxxx-xxxx``). Then run:

   .. code-block:: bash

      kubectl logs -f <pod-name>

   Look for entries in the log indicating LMCache is enabled and operational. An example output (indicating KV cache is stored) is:

   .. code-block:: text

      INFO 01-21 20:16:58 lmcache_connector.py:41] Initializing LMCacheConfig under kv_transfer_config kv_connector='LMCacheConnector' kv_buffer_device='cuda' kv_buffer_size=1000000000.0 kv_role='kv_both' kv_rank=None kv_parallel_size=1 kv_ip='127.0.0.1' kv_port=14579
      INFO LMCache: Creating LMCacheEngine instance vllm-instance [2025-01-21 20:16:58,732] -- /usr/local/lib/python3.12/dist-packages/lmcache/experimental/cache_engine.py:237

2. Forward the router service port to access the stack locally:

   .. code-block:: bash

      kubectl port-forward svc/vllm-router-service 30080:80

3. Send a request to the stack and observe the logs:

   .. code-block:: bash

      curl -X POST http://localhost:30080/v1/completions \
        -H "Content-Type: application/json" \
        -d '{
          "model": "mistralai/Mistral-7B-Instruct-v0.2",
          "prompt": "Explain the significance of KV cache in language models.",
          "max_tokens": 10
        }'

   Expected output:

   The response from the stack should contain the completion result, and the logs should show LMCache activity, for example:

   .. code-block:: text

      DEBUG LMCache: Store skips 0 tokens and then stores 13 tokens [2025-01-21 20:23:45,113] -- /usr/local/lib/python3.12/dist-packages/lmcache/integration/vllm/vllm_adapter.py:490

Benchmark the Performance Gain of Remote Shared Storage (Work in Progress)
---------------------------------------------------------------------------

In this section, we will benchmark the performance improvement when using LMCache for remote KV cache shared storage. Stay tuned for updates.

Conclusion
----------

This tutorial demonstrated how to enable a shared KV cache storage across multiple vllm nodes in a vLLM deployment using LMCache. By storing KV cache to a remote shared storage, you can improve KV cache hit rate and potentially make the deployment more fault tolerant. Explore further configurations to tailor LMCache to your workloads.
