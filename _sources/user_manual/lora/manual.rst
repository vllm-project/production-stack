.. _lora_manual:

Manually Load LORA
===================

Download LoRA adapters
----------------------

Download a LoRA adapter from HuggingFace to your persistent volume:
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Get into the vLLM pod
    kubectl exec -it $(kubectl get pods | grep vllm-lora-llama2-7b-deployment-vllm | awk '{print $1}') -- bash

    # Inside the pod, download the adapter using Python
    mkdir -p /data/lora-adapters
    cd /data/lora-adapters
    python3 -c "
    from huggingface_hub import snapshot_download
    adapter_id = 'yard1/llama-2-7b-sql-lora-test'  # Example SQL adapter
    sql_lora_path = snapshot_download(
        repo_id=adapter_id,
        local_dir='./sql-lora',
        token=__import__('os').environ['HUGGING_FACE_HUB_TOKEN']
    )
    "

    # Verify the adapter files are downloaded
    ls -l /data/lora-adapters/sql-lora


Access the vLLM API
~~~~~~~~~~~~~~~~~~~~~~~~

Set up port forwarding to access the vLLM API:

.. code-block:: bash

   kubectl port-forward svc/vllm-lora-router-service 8000:80


Verify the connection in a new terminal:

.. code-block:: bash

    curl http://localhost:8000/v1/models


Load and list the models
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Forward the port to the vLLM service:

.. code-block:: bash

    kubectl port-forward svc/vllm-lora-engine-service 8001:80


List available models:

.. code-block:: bash

    curl http://localhost:8001/v1/models


Load the SQL LoRA adapter:

.. code-block:: bash

    curl -X POST http://localhost:8001/v1/load_lora_adapter \
        -H "Content-Type: application/json" \
        -d '{
            "lora_name": "sql_adapter",
            "lora_path": "/data/lora-adapters/sql-lora"
        }'

Generate Text with LoRA
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Send a query to the vLLM API to generate text using the loaded LoRA adapter:

.. code-block:: bash

    curl -X POST http://localhost:8000/v1/completions \
        -H "Content-Type: application/json" \
        -d '{
            "model": "meta-llama/Llama-2-7b-hf",
            "prompt": "Write a SQL query to select all users who have made a purchase in the last 30 days",
            "max_tokens": 100,
            "temperature": 0.7,
            "lora_adapter": "sql_adapter"
        }'


Unload the adapter:

.. code-block:: bash

    curl -X POST http://localhost:8001/v1/unload_lora_adapter \
        -H "Content-Type: application/json" \
        -d '{
            "lora_name": "sql_adapter"
        }'
