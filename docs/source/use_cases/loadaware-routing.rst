Load Aware Routing
==================

In this tutorial, you'll learn how to enable and use load aware routing in the vLLM Production Stack. Load aware routing extends KV cache aware routing by weighing the cache-hit benefit of each instance against its live load. With plain KV cache aware routing, every request that matches a popular cached prefix is sent to the one instance holding that prefix, however busy it is — the hot instance queues while its peers sit idle. Load aware routing scores **every** instance and can send a request to a cold-but-idle instance when the warm one is saturated.

Table of Contents
-----------------

1. Prerequisites_
2. `How It Works`_
3. `Step 1: Deploy with Load Aware Routing`_
4. `Step 2: Port Forwarding`_
5. `Step 3: Testing Load Aware Routing`_
6. `Step 4: Clean Up`_
7. `Tuning beta`_

Prerequisites
-------------

- Completion of the following tutorials:

  - :doc:`../getting_started/prerequisite`
  - :doc:`../getting_started/quickstart`

- A Kubernetes environment with GPU support
- Basic familiarity with Kubernetes and Helm
- Familiarity with :doc:`kv-cache-aware-routing` is helpful, since load aware routing builds on the same LMCache controller setup

How It Works
------------

For each request, the router scores every endpoint:

.. code-block:: text

   score(i) = matched_tokens(i) / prompt_tokens - beta * relative_load(i)

   relative_load(i) = (load(i) - mean_load) / max(1, mean_load)

and routes the request to the endpoint with the highest score. ``matched_tokens`` comes from the LMCache controller's lookup (how much of the prompt is already cached on that instance), and ``load`` is the number of in-flight requests on the endpoint.

Design notes:

1. **The cache benefit is normalized** to the fraction of the prompt already cached (0 to 1) rather than a raw token count, so one ``beta`` means the same policy for a 500-token and a 4000-token prompt.
2. **Load is normalized against the fleet's own mean.** An absolute in-flight count has no bounded scale — it depends on request rate, prompt length, and GPU — so the same ``beta`` would be a different policy on every deployment. A relative load of 0.0 means "average", +1.0 means "twice the fleet average". The denominator is clamped at 1 so an essentially idle fleet reports no imbalance to act on.
3. **Every endpoint is scored**, not only the cache holders. An endpoint with nothing cached scores benefit 0 — that is what makes "cold but idle beats warm but loaded" expressible at all.
4. ``kv_aware_threshold`` **is not applied.** KV cache aware routing needs that band because it cannot weigh a small match against anything; the argmax can — a small match simply loses to load.

When the controller reports no cache holder at all, placement falls back to the router's session-hash / QPS route, exactly like KV cache aware routing.

Step 1: Deploy with Load Aware Routing
--------------------------------------

Load aware routing uses the same LMCache controller setup as KV cache aware routing, so we can reuse the predefined configuration file ``values-17-kv-aware.yaml`` and only switch the routing logic:

.. code-block:: bash

   helm install vllm helm/ -f tutorials/assets/values-17-kv-aware.yaml \
     --set routerSpec.routingLogic=loadaware

Note that to add more instances, you need to specify different ``instanceId`` in ``lmcacheConfig``.

Wait for the deployment to complete:

.. code-block:: bash

   kubectl get pods -w

Step 2: Port Forwarding
-----------------------

Forward the router service port to your local machine:

.. code-block:: bash

   kubectl port-forward svc/vllm-router-service 30080:80

Step 3: Testing Load Aware Routing
----------------------------------

First, send a request to the router:

.. code-block:: bash

   curl http://localhost:30080/v1/completions \
     -H "Content-Type: application/json" \
     -d '{
       "model": "openai/gpt-oss-20b",
       "prompt": "What is the capital of France?",
       "max_tokens": 100
     }'

Then, send another request with the same prompt prefix:

.. code-block:: bash

   curl http://localhost:30080/v1/completions \
     -H "Content-Type: application/json" \
     -d '{
       "model": "openai/gpt-oss-20b",
       "prompt": "What is the capital of France? And what is its population?",
       "max_tokens": 100
     }'

On an idle fleet, the second request is routed to the same instance as the first — the cache-hit benefit dominates and load aware routing behaves like KV cache aware routing. The difference appears under load: if you send many concurrent requests sharing the same prefix (for example with a load generator), you will see requests spill over to the other instance once the cache holder's load rises far enough above the fleet average to outweigh the cache benefit. The router logs each decision:

.. code-block:: text

   Routing request to http://... found by loadaware router

and with ``--log-level debug`` it logs the per-endpoint scores.

Step 4: Clean Up
-----------------

To clean up the deployment:

.. code-block:: bash

   helm uninstall vllm

Tuning beta
-----------

``beta`` is the single tunable: the exchange rate between cache benefit and load. ``beta = 1.0`` (the default) reads as "an endpoint sitting 100% above fleet-average load is docked one full cache hit's worth of preference". Because both score terms are dimensionless, the default is portable across hardware, models, and fleet sizes.

- **Lower beta** (e.g. ``0.25``) favors cache hits: requests stick to cache holders longer before spilling over. Useful when prefills are expensive (long shared prefixes) and some queueing is acceptable.
- **Higher beta** (e.g. ``2.0``) favors load balancing: requests spill to idle instances sooner, at the cost of more cache misses.
- ``beta = 0`` reproduces cache-only placement; a very large ``beta`` approaches least-loaded routing.

``beta`` can be set two ways:

1. The ``--loadaware-beta`` router flag, e.g. via ``routerSpec.extraArgs`` in the Helm values:

   .. code-block:: yaml

      routerSpec:
        routingLogic: "loadaware"
        extraArgs:
          - "--loadaware-beta"
          - "0.5"

2. The ``LOADAWARE_BETA`` environment variable on the router, which lets you adjust the weight on a running deployment without changing the router's command line. The explicit flag takes precedence over the environment variable.

Conclusion
----------

In this tutorial, we've demonstrated how to:

1. Deploy vLLM Production Stack with load aware routing
2. Set up port forwarding to access the router
3. Test the load aware routing functionality
4. Tune the ``beta`` parameter to trade cache affinity against load balance

Load aware routing keeps the cache-hit benefits of KV cache aware routing while preventing popular prefixes from concentrating load on a single instance.
