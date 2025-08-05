Prefix Aware Routing
====================

This tutorial demonstrates how to use prefix aware routing in the vLLM Production Stack. Prefix aware routing ensures that subsequent requests with the same prompt prefix are routed to the same instance, maximizing KV cache utilization and improving performance.

Table of Contents
-----------------

1. Prerequisites_
2. `Step 1: Deploy with Prefix Aware Routing`_
3. `Step 2: Port Forwarding`_
4. `Step 3: Testing Prefix Aware Routing`_
5. `Step 4: Clean Up`_

Prerequisites
-------------

- Completion of the following tutorials:

  - :doc:`../getting_started/prerequisite`
  - :doc:`../getting_started/quickstart`

- A Kubernetes environment with GPU support
- Basic familiarity with Kubernetes and Helm

Step 1: Deploy with Prefix Aware Routing
----------------------------------------

We'll use the predefined configuration file ``values-18-prefix-aware.yaml`` which sets up two vLLM instances with prefix aware routing enabled.

1. Deploy the Helm chart with the configuration:

   .. code-block:: bash

      helm install vllm helm/ -f tutorials/assets/values-18-prefix-aware.yaml

   Wait for the deployment to complete:

   .. code-block:: bash

      kubectl get pods -w

Step 2: Port Forwarding
-----------------------

Forward the router service port to your local machine:

.. code-block:: bash

   kubectl port-forward svc/vllm-router-service 30080:80

Step 3: Testing Prefix Aware Routing
------------------------------------

First, send a request to the router:

.. code-block:: bash

   curl http://localhost:30080/v1/completions \
     -H "Content-Type: application/json" \
     -d '{
       "model": "meta-llama/Llama-3.2-1B-Instruct",
       "prompt": "What is the capital of France?",
       "max_tokens": 100
     }'

Then, send another request with the same prompt prefix:

.. code-block:: bash

   curl http://localhost:30080/v1/completions \
     -H "Content-Type: application/json" \
     -d '{
       "model": "meta-llama/Llama-3.2-1B-Instruct",
       "prompt": "What is the capital of France? And what is its population?",
       "max_tokens": 100
     }'

You should observe that the second request is routed to the same instance as the first request. This is because the prefix aware router detects that the second request shares a prefix with the first request and routes it to the same instance to maximize KV cache utilization.

Specifically, you should see some log like the following:

.. code-block:: bash

   [2025-06-03 06:16:28,963] LMCache DEBUG: Scheduled to load 5 tokens for request cmpl-306538839e87480ca5604ecc5f75c847-0 (vllm_v1_adapter.py:299:lmcache.integration.vllm.vllm_v1_adapter)
   [2025-06-03 06:16:28,966] LMCache DEBUG: Retrieved 6 out of 6 out of total 6 tokens (cache_engine.py:330:lmcache.experimental.cache_engine)

Step 4: Clean Up
-----------------

To clean up the deployment:

.. code-block:: bash

   helm uninstall vllm

Conclusion
----------

In this tutorial, we've demonstrated how to:

1. Deploy vLLM Production Stack with prefix aware routing
2. Set up port forwarding to access the router
3. Test the prefix aware routing functionality

The prefix aware routing feature helps improve performance by ensuring that requests with shared prefixes are routed to the same instance, maximizing KV cache utilization.
