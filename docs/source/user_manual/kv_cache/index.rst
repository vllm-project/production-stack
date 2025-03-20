.. _kv_cache_index:

KV Cache Offloading
===================

Eenable KV cache offloading using LMCache in a vLLM deployment. KV cache offloading moves large KV caches from GPU memory to CPU or disk, enabling more potential KV cache hits. vLLM Production Stack uses LMCache for KV cache offloading. For more details, see the LMCache GitHub `repository <https://github.com/LMCache/LMCache>`_.

KV Cache Offloading Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use the following yaml

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


Deploy the Stack using Helm as shown in the :ref:`examples` section.
