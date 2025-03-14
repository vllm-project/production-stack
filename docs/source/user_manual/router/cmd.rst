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
- ``--callbacks``: The path to the callback instance extending CustomCallbackHandler (e.g. ``my_callbacks.my_callback_handler_instance``).


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


Hooking into custom callbacks
-----------------------------

The router can be extended to add custom callbacks at various points in the request lifecycle.

For this you will need to create a custom callback handler instance, implementing at least one of the available callback methods. You can find all available callbacks along with detailed descriptions in the abstract `CustomCallbackHandler <https://github.com/vllm-project/production-stack/tree/main/src/vllm_router/services/callbacks_service/custom_callbacks.py>`_ class.

.. code-block:: python

    # my_callbacks.py

    from fastapi import Request, Response

    from vllm_router.services.callbacks_service.custom_callbacks import CustomCallbackHandler


    class MyCustomCallbackHandler(CustomCallbackHandler):
        def pre_request(self, request: Request, request_body: bytes, request_json: any) -> Response | None:
            """
            Receives the request object before it gets proxied.
            """
            if b"coffee" in request_body:
                return Response("I'm a teapot", 418)

        def post_request(self, request: Request, response_content: bytes) -> None:
            """
            Is executed as a background task, receives the request object
            and the complete response_content.
            """
            with open("/tmp/response.txt", "ab") as f:
                f.write(response_content)


    my_callback_handler_instance = MyCustomCallbackHandler()


You can pass the instance to the router with the filename first (without the file ending), followed by the instance, separated by a dot like this:

.. code-block:: bash

    vllm-router ... --callbacks my_callbacks.my_callback_handler_instance
