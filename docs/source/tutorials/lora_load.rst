.. tutorial_lora_load:

LORA Loading
============

Setting up vLLM with Llama-2 and LoRA Support

Introduction
------------

This tutorial guides you through setting up the vLLM Production Stack with Llama-2-7b and LoRA adapter support. This setup enables you to use and switch between different LoRA adapters at runtime.

Prerequisites
-------------

- All prerequisites from the minimal installation tutorial are met.

- A Hugging Face account with access to ``Llama-2-7b``

- Accepted terms for ``meta-llama/Llama-2-7b-hf`` on Hugging Face

- A valid Hugging Face token

Steps
-----

1. Set up Hugging Face Credentials
++++++++++++++++++++++++++++++++++

First, create a Kubernetes secret with your Hugging Face token:

.. code:: bash

    kubectl create secret generic huggingface-credentials --from-literal=HUGGING_FACE_HUB_TOKEN=your_token_here


2. Deploy vLLM Instance with LoRA Support
++++++++++++++++++++++++++++++++++++++++++

Locate the file under path ``tutorial/assets/values-07-lora-enabled.yaml`` with the following content:

.. code-block:: yaml

    servingEngineSpec:
    runtimeClassName: ""
    modelSpec:
    - name: "llama2-7b"
        repository: "vllm/vllm-openai"
        tag: "latest"
        modelURL: "meta-llama/Llama-2-7b-hf"

        # Enable LoRA support
        enableLoRA: true

        # Mount Hugging Face credentials and configure LoRA settings
        env:
        - name: HUGGING_FACE_HUB_TOKEN
            valueFrom:
            secretKeyRef:
                name: huggingface-credentials
                key: HUGGING_FACE_HUB_TOKEN
        - name: VLLM_ALLOW_RUNTIME_LORA_UPDATING
            value: "True"

        replicaCount: 1

        # Resource requirements for Llama-2-7b
        requestCPU: 8
        requestMemory: "32Gi"
        requestGPU: 1

        # Optional: Configure storage for LoRA weights
        volumes:
        - name: lora-storage
            emptyDir: {}
        volumeMounts:
        - name: lora-storage
            mountPath: "/lora-weights"


Deploy the Helm chart using the predefined configuration file.

.. code-block:: bash

    helm repo add vllm https://vllm-project.github.io/production-stack
    helm install vllm-lora ./helm -f tutorials/assets/values-07-lora-enabled.yaml

3. Download LoRA adapters
+++++++++++++++++++++++++

3.1 Download a LoRA adapter from HuggingFace to your persistent volume:
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


3.2 Access the vLLM API
~~~~~~~~~~~~~~~~~~~~~~~~

Set up port forwarding to access the vLLM API:

.. code-block:: bash

   kubectl port-forward svc/vllm-lora-router-service 8000:80


Verify the connection in a new terminal:

.. code-block:: bash

    curl http://localhost:8000/v1/models


3.3 Load and list the models
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

3.4 Generate Text with LoRA
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

4. Monitoring the status
+++++++++++++++++++++++++

Monitor the deployment status:

.. code-block:: bash

    kubectl get pods


Expected output:

.. code-block:: bash

    NAME                                            READY      STATUS    RESTARTS       AGE
    vllm-lora-deployment-router-xxxxxx-yyyy           1/1     Running        0          2m38s
    vllm-lora-llama2-7b-deployment-xxxxxx-yyyy        1/1     Running        0          2m38s

5. Troubleshooting
+++++++++++++++++++

Common issues and solutions:

- Hugging Face Authentication:

    + Verify your token is correctly set in the Kubernetes secret

    + Check pod logs for authentication errors


- Resource Issues:

    + Ensure your cluster has sufficient GPU memory

    + Monitor GPU utilization using ``nvidia-smi``



- LoRA Loading Issues:

    * Verify LoRA weights are in the correct format

    * Check pod logs for adapter loading errors



6. Cleanup
+++++++++++

To remove the deployment:

.. code-block:: bash

    helm uninstall vllm-lora
    kubectl delete secret huggingface-credentials


Additional Resources
+++++++++++++++++++++

`vLLM LoRA Documentation <https://docs.vllm.ai>`_

`Llama-2 Model Card <https://huggingface.co/meta-llama/Llama-2-7b-hf>`_

`LoRA Paper <https://arxiv.org/abs/2106.09685>`_
