Docker Guide
============

This section provides information about Docker containerization and custom image development for the vLLM Production Stack.

Build Docker Image
------------------

.. code-block:: bash

   docker build -t <image_name>:<tag> -f docker/Dockerfile .

Example Commands to Run the Router
-----------------------------------

You can install the router using the following command:

.. code-block:: bash

   pip install -e .

If you want to run the router with the semantic cache, you can install the dependencies using the following command:

.. code-block:: bash

   pip install -e .[semantic_cache]

Example 1: running the router locally at port 8000 in front of multiple serving engines:

.. code-block:: bash

   vllm-router --port 8000 \
       --service-discovery static \
       --static-backends "http://localhost:9001,http://localhost:9002,http://localhost:9003" \
       --static-models "facebook/opt-125m,meta-llama/Llama-3.1-8B-Instruct,facebook/opt-125m" \
       --static-aliases "gpt4:meta-llama/Llama-3.1-8B-Instruct" \
       --static-model-types "chat,chat,chat" \
       --static-backend-health-checks \
       --engine-stats-interval 10 \
       --log-stats \
       --routing-logic roundrobin
