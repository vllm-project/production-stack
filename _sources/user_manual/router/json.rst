.. _json:

JSON based configuration
=====================================

The router can be configured dynamically using a json file when passing the ``--dynamic-config-json`` option. The router will watch the json file for changes and update the configuration accordingly (every 10 seconds).

Currently, the dynamic config supports the following fields:

Required fields:

* ``service_discovery``: The service discovery type. Options are ``static`` or ``k8s``.
* ``routing_logic``: The routing logic to use. Options are ``roundrobin`` or ``session``.


Optional fields:

* (When using static service discovery) ``static_backends``: The URLs of static serving engines, separated by commas (e.g., ``http://localhost:9001,http://localhost:9002,http://localhost:9003``).
* (When using static service discovery) ``static_models``: The models running in the static serving engines, separated by commas (e.g., ``model1,model2``).
* (When using k8s service discovery) ``k8s_port``: The port of vLLM processes when using ``K8s`` service discovery. Default is ``8000``.
* (When using k8s service discovery) ``k8s_namespace``: The namespace of vLLM pods when using K8s service discovery. Default is ``default``.
* (When using k8s service discovery) ``k8s_label_selector``: The label selector to filter vLLM pods when using ``K8s`` service discovery.
* session_key: The key (in the header) to identify a session when using session-based routing.


Example dynamic config file:

.. code-block:: json

    {
    "service_discovery": "static",
    "routing_logic": "roundrobin",
    "static_backends": "http://localhost:9001,http://localhost:9002,http://localhost:9003",
    "static_models": "facebook/opt-125m,meta-llama/Llama-3.1-8B-Instruct,facebook/opt-125m"
    }

Get current dynamic config
--------------------------

If the dynamic config is enabled, the router will reflect the current dynamic config in the ``/health`` endpoint.

.. code-block:: bash

    curl http://<router_host>:<router_port>/health


The response will be a JSON object with the current dynamic config.

.. code-block:: json

    {
    "status": "healthy",
    "dynamic_config": "<current_dynamic_config (JSON object)>"
    }
