Helm Chart Deployment
=====================

This tutorial guides you through the basic configurations required to deploy a vLLM serving engine in a Kubernetes environment with GPU support. You will learn how to specify the model details, set up necessary environment variables (like ``HF_TOKEN``), and launch the vLLM serving engine.

Table of Contents
-----------------

1. Prerequisites_
2. `Step 1: Preparing the Configuration File`_
3. `Step 2: Applying the Configuration`_
4. `Step 3: Verifying the Deployment`_
5. `Step 4 (Optional): Multi-GPU Deployment`_

Prerequisites
-------------

- A Kubernetes environment with GPU support, as set up in the :doc:`../getting_started/prerequisite` tutorial.
- Helm installed on your system.
- Access to a HuggingFace token (``HF_TOKEN``).

Step 1: Preparing the Configuration File
----------------------------------------

1. Locate the example configuration file `tutorials/assets/values-02-basic-config.yaml <https://github.com/vllm-project/production-stack/blob/main/tutorials/assets/values-02-basic-config.yaml>`_.
2. Open the file and update the following fields:
    - Write your actual huggingface token in ``hf_token: <YOUR HF TOKEN>`` in the yaml file.

Explanation of Key Items in ``values-02-basic-config.yaml``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **name**: The unique identifier for your model deployment.
- **repository**: The Docker repository containing the model's serving engine image.
- **tag**: Specifies the version of the model image to use.
- **modelURL**: The URL pointing to the model on Hugging Face or another hosting service.
- **replicaCount**: The number of replicas for the deployment, allowing scaling for load.
- **requestCPU**: The amount of CPU resources requested per replica.
- **requestMemory**: Memory allocation for the deployment; sufficient memory is required to load the model.
- **requestGPU**: Specifies the number of GPUs to allocate for the deployment.
- **pvcStorage**: Defines the Persistent Volume Claim size for model storage.
- **vllmConfig**: Contains model-specific configurations:

  - ``enableChunkedPrefill``: Optimizes performance by prefetching model chunks.
  - ``enablePrefixCaching``: Speeds up response times for common prefixes in queries.
  - ``maxModelLen``: The maximum sequence length the model can handle.
  - ``dtype``: Data type for computations, e.g., ``bfloat16`` for faster performance on modern GPUs.
  - ``extraArgs``: Additional arguments passed to the vLLM engine for fine-tuning behavior.

- **hf_token**: The Hugging Face token for authenticating with the Hugging Face model hub.
- **env**: Extra environment variables to pass to the model-serving engine.

Example Snippet
~~~~~~~~~~~~~~~

.. code-block:: yaml

   servingEngineSpec:
     modelSpec:
     - name: "llama3"
       repository: "vllm/vllm-openai"
       tag: "latest"
       modelURL: "meta-llama/Llama-3.1-8B-Instruct"
       replicaCount: 1

       requestCPU: 10
       requestMemory: "16Gi"
       requestGPU: 1

       pvcStorage: "50Gi"

       vllmConfig:
         enableChunkedPrefill: false
         enablePrefixCaching: false
         maxModelLen: 16384
         dtype: "bfloat16"
         extraArgs: ["--disable-log-requests", "--gpu-memory-utilization", "0.8"]

       hf_token: <YOUR HF TOKEN>

Step 2: Applying the Configuration
----------------------------------

Deploy the configuration using Helm:

.. code-block:: bash

   helm repo add vllm https://vllm-project.github.io/production-stack
   helm install vllm vllm/vllm-stack -f tutorials/assets/values-02-basic-config.yaml

Expected output:

You should see output indicating the successful deployment of the Helm chart:

.. code-block:: text

   Release "vllm" has been deployed. Happy Helming!
   NAME: vllm
   LAST DEPLOYED: <timestamp>
   NAMESPACE: default
   STATUS: deployed
   REVISION: 1

Step 3: Verifying the Deployment
---------------------------------

1. Check the status of the pods:

   .. code-block:: bash

      kubectl get pods

   Expected output:

   You should see the following pods:

   .. code-block:: text

      NAME                                             READY   STATUS    RESTARTS   AGE
      pod/vllm-deployment-router-xxxx-xxxx         1/1     Running   0          3m23s
      vllm-llama3-deployment-vllm-xxxx-xxxx        1/1     Running   0          3m23s

   - The ``vllm-deployment-router`` pod acts as the router, managing requests and routing them to the appropriate model-serving pod.
   - The ``vllm-llama3-deployment-vllm`` pod serves the actual model for inference.

2. Verify the service is exposed correctly:

   .. code-block:: bash

      kubectl get services

   Expected output:

   Ensure there are services for both the serving engine and the router:

   .. code-block:: text

      NAME                      TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)        AGE
      vllm-engine-service   ClusterIP   10.103.98.170    <none>        80/TCP    4m
      vllm-router-service   ClusterIP   10.103.110.107   <none>        80/TCP    4m

   - The ``vllm-engine-service`` exposes the serving engine.
   - The ``vllm-router-service`` handles routing and load balancing across model-serving pods.

3. Test the health endpoint:

   .. code-block:: bash

      curl http://<SERVICE_IP>/health

   Replace ``<SERVICE_IP>`` with the external IP of the service. If everything is configured correctly, you will get:

   .. code-block:: text

      {"status":"healthy"}

Please refer to Step 3 in the :doc:`../getting_started/quickstart` tutorial for querying the deployed vLLM service.

Step 4 (Optional): Multi-GPU Deployment
---------------------------------------

So far, you have configured and deployed a vLLM serving engine with a single GPU. You may also deploy a serving engine on multiple GPUs with the following example configuration snippet:

.. code-block:: yaml

   servingEngineSpec:
     runtimeClassName: ""
     modelSpec:
     - name: "llama3"
       repository: "vllm/vllm-openai"
       tag: "latest"
       modelURL: "meta-llama/Llama-3.1-8B-Instruct"
       replicaCount: 1
       requestCPU: 10
       requestMemory: "16Gi"
       requestGPU: 2
       pvcStorage: "50Gi"
       pvcAccessMode:
         - ReadWriteOnce
       vllmConfig:
         enableChunkedPrefill: false
         enablePrefixCaching: false
         maxModelLen: 4096
         tensorParallelSize: 2
         dtype: "bfloat16"
         extraArgs: ["--disable-log-requests", "--gpu-memory-utilization", "0.8"]
       hf_token: <YOUR HF TOKEN>
       shmSize: "20Gi"

Note that only tensor parallelism is supported for now. The field ``shmSize`` has to be configured if you are requesting ``requestGPU`` to be more than one, to enable appropriate shared memory across multiple processes used to run tensor parallelism.

Conclusion
----------

In this tutorial, you configured and deployed a vLLM serving engine with GPU support (both on a single GPU or multiple GPUs) in a Kubernetes environment. You also learned how to verify its deployment and ensure it is running as expected. For further customization, refer to the ``values.yaml`` file and Helm chart documentation.
