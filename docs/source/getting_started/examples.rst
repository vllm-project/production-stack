.. _examples:

Minimal Example
===============

Introduction
------------

This is a minimal working example of the vLLM Production Stack using one vLLM instance with the ``facebook/opt-125m`` model.
The goal is to have a working deployment of vLLM on a Kubernetes environment with GPU.

Prerequisites
-------------

- A Kubernetes environment with GPU support. If not set up, follow the `install-kubernetes-env <https://github.com/vllm-project/production-stack/blob/main/tutorials/00-install-kubernetes-env.md>`_ guide.
- Helm installed. Refer to the `install-helm.sh <https://github.com/vllm-project/production-stack/blob/main/utils/install-helm.sh>`_ script for instructions.
- kubectl should be installed. Refer to the `install-kubectl.sh <https://github.com/vllm-project/production-stack/blob/main/utils/install-kubectl.sh>`_ script for instructions.
- The project repository cloned: `vLLM Production Stack repository <https://github.com/vllm-project/production-stack>`_.
- Basic familiarity with Kubernetes and Helm.

Steps to follow
---------------

1. Deploy vLLM Instance
~~~~~~~~~~~~~~~~~~~~~~~~

1.1 Use existing configuration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The vLLM Production Stack repository provides a predefined configuration file, `values-01-minimal-example.yaml`, located `here <https://github.com/vllm-project/production-stack/blob/main/tutorials/assets/values-01-minimal-example.yaml>`_.
This file contains the following content:

.. code-block:: yaml

    servingEngineSpec:
    runtimeClassName: ""
    modelSpec:
    - name: "opt125m"
        repository: "vllm/vllm-openai"
        tag: "latest"
        modelURL: "facebook/opt-125m"

        replicaCount: 1

        requestCPU: 6
        requestMemory: "16Gi"
        requestGPU: 1


1.2 Deploy the stack
^^^^^^^^^^^^^^^^^^^^

Deploy the Helm chart using the predefined configuration file:

.. code-block:: bash

    sudo helm repo add vllm https://vllm-project.github.io/production-stack
    sudo helm install vllm vllm/vllm-stack -f tutorials/assets/values-01-minimal-example.yaml


2. Validate Installation
~~~~~~~~~~~~~~~~~~~~~~~~

2.1 Monitor Deployment Status
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Monitor the deployment status using:

.. code-block:: bash

    sudo kubectl get pods


Expected output:

.. code-block:: console

    NAME                                           READY   STATUS    RESTARTS   AGE
    vllm-deployment-router-859d8fb668-2x2b7        1/1     Running   0          2m38s
    vllm-opt125m-deployment-vllm-84dfc9bd7-vb9bs   1/1     Running   0          2m38s

.. note::

    It may take some time for the containers to download the Docker images and LLM weights.

3. Send a Query to the Stack
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

3.1 Forward the Service Port
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Expose the `vllm-router-service` port to the host machine:

.. code-block:: bash

    sudo kubectl port-forward svc/vllm-router-service 30080:80


3.2 Query the OpenAI-Compatible API to list the available models
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Test the stack's OpenAI-compatible API by querying the available models:

.. code-block:: bash

    curl -o- http://localhost:30080/models


Expected output:

.. code-block:: json

    {
      "object": "list",
      "data": [
        {
          "id": "facebook/opt-125m",
          "object": "model",
          "created": 1737428424,
          "owned_by": "vllm",
          "root": null
        }
      ]
    }



3.3 Query the OpenAI Completion Endpoint
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Send a query to the OpenAI `/completion` endpoint to generate a completion for a prompt:

.. code-block:: bash

    curl -X POST http://localhost:30080/completions \
      -H "Content-Type: application/json" \
      -d '{
        "model": "facebook/opt-125m",
        "prompt": "Once upon a time,",
        "max_tokens": 10
      }'


Expected output:

.. code-block:: json

    {
      "id": "completion-id",
      "object": "text_completion",
      "created": 1737428424,
      "model": "facebook/opt-125m",
      "choices": [
        {
          "text": " there was a brave knight who...",
          "index": 0,
          "finish_reason": "length"
        }
      ]
    }


4. Uninstall
~~~~~~~~~~~~

To remove the deployment, run:

.. code-block:: bash

    sudo helm uninstall vllm
