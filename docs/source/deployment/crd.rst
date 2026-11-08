
.. _crd_deployment:

CRD Deployment
=======================================

Deploy minimal vLLM production stack on Kubernetes using Custom Resource Definitions (CRDs) and Custom Resources (CRs).

.. note::
   This deployment method is **recommended** for production environments as it provides better resource management, monitoring, and lifecycle management through Kubernetes operators.

Prerequisites
-------------

- **kubectl** version v1.11.3+
- Access to a Kubernetes v1.11.3+ cluster

Installation
------------

1. **Clone the repository**

   First, clone the vLLM production stack repository:

   .. code-block:: bash

      git clone https://github.com/vllm-project/production-stack.git

2. **Deploy the Operator**

   Deploy the production stack operator by running:

   .. code-block:: bash

      kubectl create -f operator/config/default.yaml

   This command achieves the following:

   - **Namespace Creation**: Creates a namespace called ``production-stack-system`` where the operator will run
   - **Custom Resource Definitions (CRDs)**: Defines 4 new custom resources that can be managed by this operator:

     - ``CacheServer``: For managing LMCache multiprocess cache servers
     - ``LoraAdapter``: For managing LoRA adapters (used for model fine-tuning)
     - ``VLLMRouter``: For managing vLLM routing
     - ``VLLMRuntime``: For managing vLLM runtime instances

   - **RBAC (Role-Based Access Control)**: Creates various roles and role bindings to control access to these resources with permissions for:

     - Admin roles (full access)
     - Editor roles (create/update/delete)
     - Viewer roles (read-only)
     - Metrics and leader election

   - **Service Account**: Creates a service account ``production-stack-controller-manager`` for the operator
   - **Deployment**: Deploys the operator controller manager as a deployment with health checks, resource limits, and security settings using the image ``lmcache/production-stack-operator:latest``
   - **Service**: Creates a metrics service for monitoring the operator

3. **Verify the Operator Deployment**

   Check the status of the operator deployment:

   .. code-block:: bash

      kubectl get pods -n production-stack-system
      kubectl get deployment -n production-stack-system

   You should see output similar to:

   .. code-block:: bash

      NAME                                                              READY   STATUS    RESTARTS   AGE
      production-stack-production-stack-controller-manager-65b86brxm6   1/1     Running   0          21s

      NAME                                                   READY   UP-TO-DATE   AVAILABLE   AGE
      production-stack-production-stack-controller-manager   1/1     1            1           25s

How the Stack Fits Together
---------------------------

A ``VLLMRuntime`` runs LMCache in one of two modes, chosen with
``lmCacheConfig.mode``:

- **Multiprocess** (the default): the KV cache lives in its own cache server
  pod, and the engines attach to it through the ``LMCacheMPConnector``. The
  rest of this section and the next describe this mode.
- **InProcess**: the KV cache lives inside the engine process, through the
  ``LMCacheConnectorV1`` KV connector, and offloads to CPU memory, local disk
  or a remote backend. No ``CacheServer`` is needed, but the cache is lost
  when the engine restarts and is not shared between replicas. See
  `In-Process Mode`_.

In multiprocess mode:

- A ``CacheServer`` runs ``lmcache server``. It keeps KV cache in host memory
  (L1) and, optionally, on a local disk (L2).
- A ``VLLMRuntime`` with ``lmCacheConfig.mode: Multiprocess`` attaches its
  engine to the cache server through the ``LMCacheMPConnector`` KV connector.
- A ``VLLMRouter`` spreads requests across the engines. Session routing keeps
  each user on one engine, so the engine's own GPU prefix cache is used
  first and the cache server covers whatever falls out of it.

Because the cache lives outside the engine, it survives engine restarts, and
every engine attached to the same cache server shares it.

The cache server uses the ``lmcache_driven`` transfer mode: it copies KV out
of the engines' GPU memory over CUDA IPC. This requires:

- The cache server and the engines on the **same GPU node**.
- GPU visibility for the cache server **without a GPU request**: an
  ``nvidia`` RuntimeClass and ``NVIDIA_VISIBLE_DEVICES=all``. The cache
  server opens one CUDA context on each engine GPU (about 700 MiB each),
  which Kubernetes does not count against the GPU.
- The **same image** for the cache server and the engines. The samples use
  ``lmcache/vllm-openai:v0.5.5``.

.. note::
   A ``CacheServer`` always runs ``lmcache server``. The standalone
   ``lmcache_server`` backend it used to run was removed from LMCache in
   0.5.7rc2, together with the ``lm://`` connector, so an in-process
   ``remoteUrl`` of the form ``lm://<cacheserver>`` no longer has a server to
   reach. Move such runtimes to ``mode: Multiprocess``, as in the samples
   below.

Deploying the Stack
-------------------

The samples are in ``operator/config/samples/``:

.. list-table::
   :header-rows: 1

   * - File
     - Creates
   * - ``cacheserver-kvcache-pv.yaml``
     - hostPath PersistentVolume on the GPU node's local drive, for the L2 tier
   * - ``cacheserver-kvcache-pvc.yaml``
     - Claim on that volume, mounted by the cache server
   * - ``production-stack_v1alpha1_cacheserver.yaml``
     - Cache server: 20 GB of KV cache in host memory plus up to 180 GB on disk
   * - ``production-stack_v1alpha1_vllmruntime.yaml``
     - vLLM engines for ``meta-llama/Llama-3.1-8B-Instruct``, attached to the
       cache server
   * - ``production-stack_v1alpha1_vllmrouter.yaml``
     - Router in front of the engines
   * - ``production-stack_v1alpha1_vllmruntime_inprocess.yaml``
     - Alternative engine in in-process mode, without a cache server (see
       `In-Process Mode`_)

1. **Create the Hugging Face token secret**

   ``meta-llama/Llama-3.1-8B-Instruct`` is a gated model, so the engine needs a
   token:

   .. code-block:: bash

      kubectl create secret generic huggingface-token \
        --from-literal=token=<your-hf-token> \
        --namespace=default

2. **Create the KV-cache disk**

   Edit ``hostPath.path`` in ``cacheserver-kvcache-pv.yaml`` to point at a
   directory on a dedicated local drive of the GPU node (NVMe is best), not
   the disk that holds etcd or the root filesystem. Then create the volume and
   its claim:

   .. code-block:: bash

      kubectl apply -f operator/config/samples/cacheserver-kvcache-pv.yaml
      kubectl apply -f operator/config/samples/cacheserver-kvcache-pvc.yaml

3. **Deploy the cache server**

   .. code-block:: bash

      kubectl apply -f operator/config/samples/production-stack_v1alpha1_cacheserver.yaml

4. **Deploy the vLLM runtime**

   .. code-block:: bash

      kubectl apply -f operator/config/samples/production-stack_v1alpha1_vllmruntime.yaml

   ``lmCacheConfig.multiprocess.host`` points at the cache server's Service.
   The engine waits for the cache server at startup, so deploy the cache
   server first.

5. **Deploy the vLLM router**

   .. code-block:: bash

      kubectl apply -f operator/config/samples/production-stack_v1alpha1_vllmrouter.yaml

6. **Verify the deployment**

   .. code-block:: bash

      kubectl get pods

   You should see the ``cacheserver-sample`` pod, two ``vllmruntime-sample``
   pods and the ``vllmrouter-sample`` pod in ``Running`` state.

   If a pod is stuck, check its logs and events:

   .. code-block:: bash

      kubectl logs <pod-name>
      kubectl describe pod <pod-name>

Sample Configurations
---------------------

**CacheServer (production-stack_v1alpha1_cacheserver.yaml)**

.. code-block:: yaml

   apiVersion: production-stack.vllm.ai/v1alpha1
   kind: CacheServer
   metadata:
     name: cacheserver-sample
   spec:
     image:
       registry: "docker.io"
       name: "lmcache/vllm-openai:v0.5.5"   # same image as the engines
       pullPolicy: "IfNotPresent"
     port: 9000                 # ZMQ port the engines connect to
     replicas: 1
     deploymentStrategy: "Recreate"
     resources:
       cpu: "4"
       memory: "32Gi"           # must cover l1SizeGb plus overhead; no GPU
     runtimeClassName: "nvidia" # see the engines' GPUs without requesting one
     env:
       - name: NVIDIA_VISIBLE_DEVICES
         value: "all"
     multiprocess:
       l1SizeGb: 20             # host DRAM tier, in GB
       evictionPolicy: LRU
       chunkSize: 256           # must match the engines
       isolatedIpc: true        # must match the VLLMRuntime
       httpPort: 8080           # Prometheus metrics
       l2Adapters:
         - '{"type": "fs_native", "base_path": "/kvcache", "max_capacity_gb": 180}'
     volumes:
       - name: kvcache
         persistentVolumeClaim:
           claimName: lmcache-kvcache
     volumeMounts:
       - name: kvcache
         mountPath: /kvcache    # base_path of the L2 adapter must sit under it

**VLLMRuntime (production-stack_v1alpha1_vllmruntime.yaml)**, the LMCache part:

.. code-block:: yaml

   apiVersion: production-stack.vllm.ai/v1alpha1
   kind: VLLMRuntime
   metadata:
     name: vllmruntime-sample
   spec:
     model:
       modelURL: "meta-llama/Llama-3.1-8B-Instruct"
       maxModelLen: 4096
     lmCacheConfig:
       enabled: true
       mode: Multiprocess          # the default; named here for clarity
       multiprocess:
         host: "tcp://cacheserver-sample.default.svc.cluster.local"
         port: 9000                # the CacheServer's spec.port
         isolatedIpc: true         # the CacheServer's multiprocess.isolatedIpc
     deploymentConfig:
       image:
         registry: "docker.io"
         name: "lmcache/vllm-openai:v0.5.5"   # same image as the cache server
       replicas: 2

**VLLMRouter (production-stack_v1alpha1_vllmrouter.yaml)**

The router needs no LMCache settings. Its ``k8sLabelSelector``,
``app=vllmruntime-sample``, selects the engines above.

Field Reference
---------------

**CacheServer** ``spec.multiprocess`` (one field per ``lmcache server`` flag;
fields left out keep the server's own default):

.. list-table::
   :header-rows: 1

   * - Field
     - Flag
     - Default
     - Notes
   * - ``l1SizeGb``
     - ``--l1-size-gb``
     - ``10``
     - Host DRAM tier in GB. Size the pod's memory above it.
   * - ``l1InitSizeGb``
     - ``--l1-init-size-gb``
     - server default
     - L1 allocated at startup; the rest is faulted in on demand.
   * - ``evictionPolicy``
     - ``--eviction-policy``
     - ``LRU``
     - ``LRU``, ``IsolatedLRU`` or ``noop``.
   * - ``chunkSize``
     - ``--chunk-size``
     - ``256``
     - Must match the engines. See `Sizing`_.
   * - ``transferMode``
     - ``--supported-transfer-mode``
     - ``lmcache_driven``
     - The only supported mode.
   * - ``isolatedIpc``
     - ``--isolated-ipc``
     - ``false``
     - Set when the server and the engines share no IPC namespace, which is
       the case for separate pods. Must match the engines.
   * - ``httpPort``
     - ``--http-port``
     - ``8080``
     - Metrics and control frontend, published on the Service as ``metrics``.
   * - ``l2Adapters``
     - ``--l2-adapter`` (repeated)
     - none
     - JSON per cold tier, for example ``fs_native`` with a ``base_path``
       under a ``volumeMount``.
   * - ``l1AlignBytes``, ``evictionTriggerWatermark``, ``evictionRatio``,
       ``maxWorkers``, ``maxGpuWorkers``, ``maxCpuWorkers``, ``instanceId``,
       ``separateObjectGroups``
     - matching flag
     - server default
     - Tuning; see ``lmcache server --help``.
   * - ``extraArgs``
     - appended verbatim
     - none
     - For flags the spec does not model.

``CacheServer`` pod fields: ``runtimeClassName``, ``env``, ``hostIPC``
(alternative to ``isolatedIpc``), ``volumes`` and ``volumeMounts``.

**VLLMRuntime** ``spec.lmCacheConfig``:

.. list-table::
   :header-rows: 1

   * - Field
     - Default
     - Notes
   * - ``enabled``
     - ``false``
     - Turns on LMCache.
   * - ``mode``
     - ``Multiprocess``
     - ``Multiprocess`` or ``InProcess``.
   * - ``cpuOffloadingBufferSize``
     - ``4Gi``
     - InProcess only. CPU offloading buffer (``LMCACHE_MAX_LOCAL_CPU_SIZE``).
   * - ``diskOffloadingBufferSize``
     - ``8Gi``
     - InProcess only. Disk offloading buffer
       (``LMCACHE_MAX_LOCAL_DISK_SIZE``). Set it to ``""`` to turn disk
       offloading off.
   * - ``remoteUrl``, ``remoteSerde``
     - none
     - InProcess only. Remote backend (``LMCACHE_REMOTE_URL``,
       ``LMCACHE_REMOTE_SERDE``).
   * - ``multiprocess.host``
     - none
     - Cache server address with scheme, for example
       ``tcp://<cacheserver>.<namespace>.svc.cluster.local``.
   * - ``multiprocess.port``
     - ``9000``
     - The ``CacheServer``'s ``spec.port``.
   * - ``multiprocess.transferMode``
     - ``lmcache_driven``
     - Must match the cache server.
   * - ``multiprocess.isolatedIpc``
     - ``false``
     - Must match the cache server.
   * - ``multiprocess.extraConfig``
     - none
     - Extra ``kv_connector_extra_config`` entries; they override the
       generated ones.

In-Process Mode
---------------

With ``mode: InProcess`` the engine keeps its own LMCache and needs no
``CacheServer``. The mode must be named, since the default is
``Multiprocess``. The sample is
``operator/config/samples/production-stack_v1alpha1_vllmruntime_inprocess.yaml``:

.. code-block:: yaml

   lmCacheConfig:
     enabled: true
     mode: InProcess
     cpuOffloadingBufferSize: "20"   # GB of CPU memory for offloaded KV
     diskOffloadingBufferSize: ""    # off; the default 8Gi uses ephemeral disk

.. code-block:: bash

   kubectl apply -f operator/config/samples/production-stack_v1alpha1_vllmruntime_inprocess.yaml

Choose in-process mode for a single engine that only needs more KV capacity
than its GPU holds. Choose multiprocess mode when the cache must survive
engine restarts or be shared by several engines.

.. note::
   Runtimes created before ``mode`` existed used in-process LMCache. After an
   upgrade they read back as ``Multiprocess``, the new default, and roll onto
   the ``LMCacheMPConnector``. Add ``mode: InProcess`` to such a runtime
   before upgrading the operator to keep its in-process cache.

Sizing
------

- **chunkSize** must be the same on the cache server and the engines. For
  hybrid (Mamba/GDN) models such as Qwen3.5 and later, it must also be a
  multiple of the attention block size vLLM picks, which the engine logs at
  startup. For example, Qwen3.8-27B with ``--mamba-cache-mode align`` uses a
  block size of 784, so ``chunkSize: 1568`` works and the default 256 fails
  registration.
- **maxNumBatchedTokens** should be a multiple of ``chunkSize``, so a prefill
  step covers whole chunks.
- **Cache server memory** must cover ``l1SizeGb`` plus a few GB of overhead.
- **L2 disk**: put the L2 path on a dedicated disk, never on the disk that
  holds etcd or the root filesystem. The L2 tier writes tens of GB within
  minutes under load, which can stall etcd long enough for controllers,
  including this operator, to lose leader election and restart.
- **GPU memory**: the cache server's CUDA context takes about 700 MiB on each
  engine GPU. Leave room for it in ``gpuMemoryUtilization``.

Testing the Deployment
----------------------

1. **Port-forward the router**

   .. code-block:: bash

      kubectl port-forward svc/vllmrouter-sample 30080:80 --address 0.0.0.0

2. **Send a request**

   In a separate terminal:

   .. code-block:: bash

      curl -X POST http://localhost:30080/v1/completions \
        -H "Content-Type: application/json" \
        -d '{
          "model": "meta-llama/Llama-3.1-8B-Instruct",
          "prompt": "1 plus 1 equals to",
          "max_tokens": 100
        }'

3. **Check that the KV cache is reused**

   Send a long prompt (a few thousand tokens), restart the engine with
   ``kubectl rollout restart deployment/vllmruntime-sample``, and send the
   same prompt again. The restarted engine has an empty GPU cache, so the
   prefix can only come from the cache server.

   - On the engine (``/metrics`` on port 8000),
     ``vllm:prompt_tokens_by_source_total{source="external_kv_transfer"}``
     rises by about the prompt length.
   - On the cache server (``/metrics`` on port 8080),
     ``lmcache_mp_lookup_hit_tokens_total`` rises by the same amount.

   If you restart the cache server too, L1 is emptied and the hits come from
   the KV-cache disk instead: ``lmcache_mp_l2_prefetch_hit_chunks_total``
   rises.

Uninstall
---------

1. **Remove Custom Resources**

   .. code-block:: bash

      kubectl delete -f operator/config/samples/production-stack_v1alpha1_vllmrouter.yaml
      kubectl delete -f operator/config/samples/production-stack_v1alpha1_vllmruntime.yaml
      kubectl delete -f operator/config/samples/production-stack_v1alpha1_cacheserver.yaml
      kubectl delete -f operator/config/samples/cacheserver-kvcache-pvc.yaml
      kubectl delete -f operator/config/samples/cacheserver-kvcache-pv.yaml

   The KV-cache volume uses the ``Retain`` reclaim policy, so the cache files
   stay on the node's disk until you delete them.

2. **Remove Secrets (if created)**

   .. code-block:: bash

      kubectl delete secret huggingface-token --namespace=default

3. **Remove the Operator and CRDs**

   Remove the entire operator deployment and custom resource definitions:

   .. code-block:: bash

      kubectl delete -f operator/config/default.yaml

4. **Verify Cleanup**

   Confirm that all resources have been removed:

   .. code-block:: bash

      kubectl get namespace production-stack-system

      kubectl get crd | grep production-stack

      kubectl get pods --all-namespaces | grep -E "(cacheserver|vllmruntime|vllmrouter)"

   You should see no results from these commands, indicating successful cleanup.

Happy deploying! 🚀
