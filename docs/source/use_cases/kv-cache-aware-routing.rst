KV Cache Aware Routing
======================

In this tutorial, you'll learn how to enable and use KV cache aware routing in the vLLM Production Stack. KV-cache-aware routing queries the LMCache controller for live, token-level cache-location data and prefers an instance that currently holds a sufficient match for the request.

How KV-Cache-Aware Routing Differs
----------------------------------

KV-cache-aware and :doc:`prefix-aware routing <prefix-aware-routing>` both aim to improve cache reuse, but they use different routing signals and can choose different endpoints.

.. list-table:: Prefix-aware and KV-cache-aware routing comparison
   :header-rows: 1
   :widths: 20 40 40

   * - Aspect
     - Prefix-aware routing
     - KV-cache-aware routing
   * - Routing signal
     - Router-local prompt-prefix history stored in an in-memory ``HashTrie``.
     - Live, token-level cache-location data queried from the LMCache controller.
   * - Cache accuracy
     - Remembers where a prefix was previously sent and assumes that placement is still useful; it does not observe cache eviction.
     - Uses the cache layout reported by LMCache, so placement reflects which instances currently hold matching cache data.
   * - Dependencies and overhead
     - Uses an in-process trie and requires no controller lookup for routing.
     - Requires LMCache controller connectivity plus tokenization and controller lookups.
   * - Request handling
     - Reads completion prompts and extracts text from chat messages.
     - The current implementation tokenizes the completion ``prompt`` field; it does not reconstruct chat messages for lookup.
   * - Fallback
     - Uses the longest remembered match. If it is shorter than a configured ``prefixMinMatchLength``, routing falls back to QPS-based placement. With the default threshold of zero and no history, it selects from the available endpoints and records that placement.
     - If no sufficient cache match exists, uses session affinity when a session ID is available and QPS-based placement otherwise.

For example, suppose the router records that a prompt prefix was sent to endpoint A. If A later evicts that cache entry while endpoint B currently holds it, prefix-aware routing may still choose A because its local trie retains the original mapping. KV-cache-aware routing queries the controller and can choose B; if no endpoint reports a sufficient match, it uses its fallback behavior.

Use prefix-aware routing when you want simple, low-overhead affinity and cache eviction is limited or predictable. Use KV-cache-aware routing when accurate cache locality across replicas matters enough to justify the LMCache controller and per-request lookup overhead.

Table of Contents
-----------------

1. Prerequisites_
2. `Step 1: Deploy with KV Cache Aware Routing`_
3. `Step 2: Port Forwarding`_
4. `Step 3: Testing KV Cache Aware Routing`_
5. `Step 4: Clean Up`_

Prerequisites
-------------

- Completion of the following tutorials:

  - :doc:`../getting_started/prerequisite`
  - :doc:`../getting_started/quickstart`

- A Kubernetes environment with GPU support
- Basic familiarity with Kubernetes and Helm

Step 1: Deploy with KV Cache Aware Routing
------------------------------------------

We'll use the predefined configuration file ``values-17-kv-aware.yaml`` which sets up two vLLM instances with KV cache aware routing enabled.

1. Deploy the Helm chart with the configuration:

   .. code-block:: bash

      helm install vllm helm/ -f tutorials/assets/values-17-kv-aware.yaml

   Note that to add more instances, you need to specify different ``instanceId`` in ``lmcacheConfig``.

   Wait for the deployment to complete:

   .. code-block:: bash

      kubectl get pods -w

Step 2: Port Forwarding
-----------------------

Forward the router service port to your local machine:

.. code-block:: bash

   kubectl port-forward svc/vllm-router-service 30080:80

Step 3: Testing KV Cache Aware Routing
--------------------------------------

First, send a request to the router:

.. code-block:: bash

   curl http://localhost:30080/v1/completions \
     -H "Content-Type: application/json" \
     -d '{
       "model": "meta-llama/Llama-3.1-8B-Instruct",
       "prompt": "What is the capital of France?",
       "max_tokens": 100
     }'

Then, send another request with the same prompt prefix:

.. code-block:: bash

   curl http://localhost:30080/v1/completions \
     -H "Content-Type: application/json" \
     -d '{
       "model": "meta-llama/Llama-3.1-8B-Instruct",
       "prompt": "What is the capital of France? And what is its population?",
       "max_tokens": 100
     }'

If the prefix cached by the first request is still available, the second request should be routed to the cache holder reported by the LMCache controller. This will often be the same instance that handled the first request, but the decision comes from the current cache layout rather than remembered request placement.

Step 4: Clean Up
-----------------

To clean up the deployment:

.. code-block:: bash

   helm uninstall vllm

Conclusion
----------

In this tutorial, we've demonstrated how to:

1. Deploy vLLM Production Stack with KV cache aware routing
2. Set up port forwarding to access the router
3. Test the KV cache aware routing functionality

KV-cache-aware routing helps improve performance by using the LMCache controller's current cache-location data to select an instance with a sufficient token-level cache match.
