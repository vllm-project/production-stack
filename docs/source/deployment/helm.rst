.. _helm_charts:

Helm Charts
=======================================

Production Stack uses Helm charts for deployment. It lets users deploy multiple serving engines and a router into the Kubernetes cluster.

Key features
------------

- Support running multiple serving engines with multiple different models
- Load the model weights directly from the existing PersistentVolumes

Prerequisites
-------------

1. A running Kubernetes cluster with GPU. (You can set it up through `minikube <https://minikube.sigs.k8s.io/docs/tutorials/nvidia/>`_)
2. `Helm <https://helm.sh/docs/intro/install/>`_ installed.

Values for Helm charts are found in a `values.yaml <https://github.com/vllm-project/production-stack/blob/main/helm/values.yaml>`_ file.

To configure the file automatically, you can use the a json file as a schema called `values.schema.json <https://github.com/vllm-project/production-stack/blob/main/helm/values.schema.json>`_.

Example ``values.yaml`` file
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: yaml

    servingEngineSpec:
        modelSpec:
        - name: "opt125m"
            repository: "lmcache/vllm-openai"
            tag: "latest"
            modelURL: "facebook/opt-125m"

            replicaCount: 1

            requestCPU: 6
            requestMemory: "16Gi"
            requestGPU: 1

            pvcStorage: "10Gi"

Explanation of the fields
-------------------------

- ``name``: The name of the model.
- ``repository``: The repository of the model to download the weights.
- ``tag``: The tag of the model to download the weights.
- ``modelURL``: The model URL to download the weights.
- ``replicaCount``: The number of replicas to run.
- ``requestCPU``: The CPU request for the serving engine.
- ``requestMemory``: The memory request for the serving engine.
- ``requestGPU``: The GPU request for the serving engine.
- ``pvcStorage``: The storage request for the serving engine.
