FAQ
===

Frequently Asked Questions about vLLM Production Stack.

Installation & Setup
---------------------

to be updated

Deployment & Configuration
---------------------------

Q: How do I update to a new version of vLLM Production Stack?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Update your ``values.yaml`` file with the new version and upgrade:

.. code-block:: bash

   helm upgrade my-vllm-stack vllm/vllm-stack -f values.yaml


Q: How do I scale my deployment?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can scale in several ways:

* **Horizontal scaling**: Increase ``replicaCount`` in your values
* **Vertical scaling**: Allocate more GPUs per replica
* **Auto-scaling**: Use :doc:`../use_cases/autoscaling-keda` for automatic scaling

Q: What's the difference between router and vLLM instances?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A:

* **Router**: Handles request routing, load balancing, and advanced features like KV cache management
* **vLLM instances**: Run the actual model inference
* The router distributes requests across multiple vLLM instances for better performance and availability

Performance & Optimization
---------------------------

Q: How can I improve inference performance?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Several optimization strategies are available:

* **KV Cache optimization**: See :doc:`../use_cases/kv-cache-aware-routing`
* **Prefix caching**: See :doc:`../use_cases/prefix-aware-routing`
* **Disaggregated prefill**: See :doc:`../use_cases/disaggregated-prefill`
* **Multiple GPU utilization**: Distribute load across multiple GPUs

Q: What is KV cache and why does it matter?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

KV (Key-Value) cache stores computed attention keys and values from previous tokens, enabling faster generation of subsequent tokens. Proper KV cache management significantly improves performance for:

* Long conversations
* Similar prompts
* Batch processing

Q: How do I monitor performance?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use the built-in monitoring features:

* **Prometheus metrics**: Built-in metrics collection
* **Distributed tracing**: See :doc:`../use_cases/distributed-tracing`
* **Benchmarking tools**: See :doc:`../use_cases/benchmarking`

Troubleshooting
---------------

Q: Pods are stuck in Pending state
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Check:

.. code-block:: bash

   kubectl describe pod <pod-name> -n vllm-system

Common causes:
* Insufficient GPU resources
* Node selector/affinity issues
* Resource quotas exceeded
* Image pull failures

Q: Where can I get help?
~~~~~~~~~~~~~~~~~~~~~~~~~

A:

* **GitHub Issues**: Report bugs and feature requests
* **Community meetings**: See :doc:`../community/meetings`
* **Documentation**: Check other sections of this documentation
* **vLLM Community**: Join the broader vLLM community discussions

Q: How can I contribute?
~~~~~~~~~~~~~~~~~~~~~~~~

See :doc:`../developer_guide/contributing` for contribution guidelines.

Q: Is there a roadmap?
~~~~~~~~~~~~~~~~~~~~~~

Check the GitHub repository for the latest roadmap and feature plans.
