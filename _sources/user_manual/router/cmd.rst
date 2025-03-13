.. _cmd:

Command Line based configuration
================================

Configuring and running the router
-----------------------------------

The router can be configured using command-line arguments. Below are the available options:

Basic Options
+++++++++++++

- ``--host``: The host to run the server on. Default is ``0.0.0.0``.
- ``--port``: The port to run the server on. Default is ``8001``.


Service Discovery Options
+++++++++++++++++++++++++

- ``--service-discovery``: The service discovery type. Options are ``static`` or ``k8s``. This option is required.
- ``--static-backends``: The URLs of static serving engines, separated by commas (e.g., ``http://localhost:8000,http://localhost:8001``).
- ``--static-models``: The models running in the static serving engines, separated by commas (e.g., ``model1,model2``).
- ``--k8s-port``: The port of vLLM processes when using K8s service discovery. Default is ``8000``.
- ``--k8s-namespace``: The namespace of vLLM pods when using K8s service discovery. Default is ``default``.
- ``--k8s-label-selector``: The label selector to filter vLLM pods when using K8s service discovery.


Routing Logic Options
+++++++++++++++++++++

- ``--routing-logic``: The routing logic to use. Options are ``roundrobin`` or ``session``. This option is required.
- ``--session-key``: The key (in the header) to identify a session.


Monitoring Options
++++++++++++++++++

- ``--engine-stats-interval``: The interval in seconds to scrape engine statistics. Default is ``30``.
- ``--request-stats-window``: The sliding window seconds to compute request statistics. Default is ``60``.


Logging Options
+++++++++++++++

- ``--log-stats``: Log statistics every 30 seconds.


Build docker image
------------------

.. code-block:: bash

    docker build -t <image_name>:<tag> -f docker/Dockerfile .


Example commands to run the router
----------------------------------

You can install the router using the following command:

.. code-block:: bash

    pip install -e .


.. raw:: html

    <b> Example : </b> running the router locally at port 8000 in front of multiple serving engines


.. code-block:: bash

    vllm-router --port 8000 \
    --service-discovery static \
    --static-backends "http://localhost:9001,http://localhost:9002,http://localhost:9003" \
    --static-models "facebook/opt-125m,meta-llama/Llama-3.1-8B-Instruct,facebook/opt-125m" \
    --engine-stats-interval 10 \
    --log-stats \
    --routing-logic roundrobin
