KV Cache Aware Routing
======================================

Introduction
------------------------------------------------

This tutorial demonstrates how to use KV cache aware routing in the vLLM Production Stack. KV cache aware routing ensures that subsequent requests with the same prompt prefix are routed to the same instance, maximizing KV cache utilization and improving performance.

Prerequisites
------------------------------------------------

* Installation of minimal example shown in :ref:`examples`
* Kubernetes environment with GPU support

Deploy with KV Cache Aware Routing
------------------------------------------------

We'll use the predefined configuration file ``values-17-kv-aware.yaml`` which sets up two vLLM instances with KV cache aware routing enabled.

1. Deploy the Helm chart with the configuration:

.. code-block:: bash

   helm install vllm helm/ -f tutorials/assets/values-17-kv-aware.yaml

Note that to add more instances, you need to specify **different** ``instanceId`` in ``lmcacheConfig``.

Wait for the deployment to complete:

.. code-block:: bash

   kubectl get pods -w

Port Forwarding
------------------------------------------------

Forward the router service port to your local machine:

.. code-block:: bash

   kubectl port-forward svc/vllm-router-service 30080:80

Testing KV Cache Aware Routing
------------------------------------------------

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

You should observe that the second request is routed to the same instance as the first request. This is because the KV cache aware router detects that the second request shares a prefix with the first request and routes it to the same instance to maximize KV cache utilization.

Clean Up
------------------------------------------------

To clean up the deployment:

.. code-block:: bash

   helm uninstall vllm

Conclusion
------------------------------------------------

In this tutorial, we've demonstrated how to:

1. Deploy vLLM Production Stack with KV cache aware routing
2. Set up port forwarding to access the router
3. Test the KV cache aware routing functionality

The KV cache aware routing feature helps improve performance by ensuring that requests with shared prefixes are routed to the same instance, maximizing KV cache utilization.
