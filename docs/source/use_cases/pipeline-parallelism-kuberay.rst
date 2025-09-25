Pipeline Parallelism with KubeRay
=================================

This tutorial provides a step-by-step guide for configuring and deploying the vLLM serving engine on a multi-node Kubernetes cluster with support for distributed inference using KubeRay. It also explains how to launch the vLLM serving engine with pipeline parallelism enabled.

Table of Contents
-----------------

1. Prerequisites_
2. `Step 1: Basic explanation of Ray and Kuberay`_
3. `Step 2: Preparing the Configuration File`_
4. `Step 3: Applying the Configuration`_
5. `Step 4: Verifying the Deployment`_

Prerequisites
-------------

- A Kubernetes cluster with multiple nodes with GPU support, as set up in the `00-a-install-multinode-kubernetes-env tutorial <https://github.com/vllm-project/production-stack/blob/main/tutorials/00-a-install-multinode-kubernetes-env.md>`_.
- Install kuberay operator on the Kubernetes environment with `00-b-install-kuberay-operator tutorial <https://github.com/vllm-project/production-stack/blob/main/tutorials/00-b-install-kuberay-operator.md>`_.
- Helm installed on your system.
- Access to a HuggingFace token (``HF_TOKEN``).
- A basic understanding of Ray is recommended. For more information, refer to the `official ray documentation <https://docs.ray.io/en/latest/cluster/kubernetes/index.html>`_.

Step 1: Basic explanation of Ray and Kuberay
--------------------------------------------

1. Ray is a framework designed for distributed workloads, such as distributed training and inference. It operates by running multiple processes—typically containers or pods—to distribute and synchronize tasks efficiently.

2. Ray organizes these processes into a Ray cluster, which consists of a single head node and multiple worker nodes. The term "node" here refers to a logical process, which can be deployed as a container or pod.

3. KubeRay is a Kubernetes operator that simplifies the creation and management of Ray clusters within a Kubernetes environment. Without KubeRay, setting up Ray nodes requires manual configuration.

4. Using KubeRay, you can easily deploy Ray clusters on Kubernetes. These clusters enable distributed inference with vLLM, supporting both tensor parallelism and pipeline parallelism.

Step 2: Preparing the Configuration File
----------------------------------------

1. Locate the example configuration file `tutorials/assets/values-15-a-minimal-pipeline-parallel-example-raycluster.yaml <https://github.com/vllm-project/production-stack/blob/main/tutorials/assets/values-15-a-minimal-pipeline-parallel-example-raycluster.yaml>`_.

2. Open the file and update the following fields:

   - Write your actual huggingface token in ``hf_token: <YOUR HF TOKEN>`` in the yaml file.

Explanation of Key Items in ``values-15-a-minimal-pipeline-parallel-example-raycluster.yaml``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **raySpec**: Required when using KubeRay to enable pipeline parallelism.
- **headNode**: Specifies the resource requirements for the Kuberay head node and must be defined accordingly:

  - **requestCPU**: The amount of CPU resources requested for Kuberay head pod.
  - **requestMemory**: Memory allocation for Kuberay head pod. Sufficient memory is required to load the model.
  - **requestGPU**: Defines the number of GPUs to allocate for the KubeRay head pod. Currently, the Ray head node must also participate in both tensor parallelism and pipeline parallelism. This requirement exists because the ``vllm serve ...`` command is executed on the Ray head node, and vLLM mandates that the pod where this command is run must have at least one visible GPU.

- **name**: The unique identifier for your model deployment.
- **repository**: The Docker repository containing the model's serving engine image.
- **tag**: Specifies the version of the model image to use.
- **modelURL**: The URL pointing to the model on Hugging Face or another hosting service.
- **replicaCount**: The number of total Kuberay worker pods.
- **requestCPU**: The amount of CPU resources requested per Kuberay worker pod.
- **requestMemory**: Memory allocation for each Kuberay worker pod. Sufficient memory is required to load the model.
- **requestGPU**: Specifies the number of GPUs to allocate for each Kuberay worker pod.
- **vllmConfig**: Contains model-specific configurations:

  - ``tensorParallelSize``: Specifies the number of GPUs assigned to each worker pod. This value must be identical to both ``requestGPU`` and ``raySpec.headNode.requestGPU``.
  - ``pipelineParallelSize``: Indicates the level of pipeline parallelism. This value must be equal to ``replicaCount + 1``, representing the total number of Ray cluster nodes, including both head and worker nodes.
  - **Important Note:**

    - The total number of GPUs required is computed as ``pipelineParallelSize × tensorParallelSize``.
    - This total must exactly match the sum of:

      - ``replicaCount × requestGPU`` (the total number of GPUs allocated to Ray worker nodes), and
      - ``raySpec.headNode.requestGPU`` (the number of GPUs allocated to the Ray head node).

    - The ``requestGPU`` value for the Ray head node must be identical to that of each worker node.
    - ``tensorParallelSize`` defines the number of GPUs allocated per Ray node (including both head and worker nodes), and must be consistent across all nodes.
    - ``pipelineParallelSize`` represents the total number of Ray nodes, and must therefore be set to replicaCount + 1 (i.e., the number of worker nodes plus the head node).

- **shmSize**: Configures the shared memory size to ensure adequate memory is available for inter-process communication during tensor and pipeline parallelism execution.
- **hf_token**: The Hugging Face token for authenticating with the Hugging Face model hub.

Example Snippet
~~~~~~~~~~~~~~~

In the following example, we configure a total of two Ray nodes each equipped with two GPUs (one head node and one worker node) to serve a distilgpt2 model. We set the tensor parallelism size to 2, as each node contains two GPUs, and the pipeline parallelism size to 2, corresponding to the two Ray nodes being utilized.

.. code-block:: yaml

   servingEngineSpec:
     runtimeClassName: ""
     modelSpec:
     - name: "distilgpt2"
       repository: "vllm/vllm-openai"
       tag: "latest"
       modelURL: "distilbert/distilgpt2"

       replicaCount: 1

       requestCPU: 2
       requestMemory: "20Gi"
       requestGPU: 2

       vllmConfig:
         tensorParallelSize: 2
         pipelineParallelSize: 2

       shmSize: "20Gi"

       raySpec:
         headNode:
           requestCPU: 2
           requestMemory: "20Gi"
           requestGPU: 2

       hf_token: <YOUR HF TOKEN>

Step 3: Applying the Configuration
----------------------------------

Deploy the configuration using Helm:

.. code-block:: bash

   helm repo add vllm https://vllm-project.github.io/production-stack
   helm install vllm vllm/vllm-stack -f tutorials/assets/values-15-a-minimal-pipeline-parallel-example-raycluster.yaml

Expected output:

You should see output indicating the successful deployment of the Helm chart:

.. code-block:: text

   NAME: vllm
   LAST DEPLOYED: Sun May 11 15:10:34 2025
   NAMESPACE: default
   STATUS: deployed
   REVISION: 1
   TEST SUITE: None

Step 4: Verifying the Deployment
---------------------------------

1. Check the status of the pods:

   .. code-block:: bash

      kubectl wait --for=condition=ready pod -l environment=router,release=router --namespace=default --timeout=60s && \
      kubectl get pods

   Expected output:

   You should see the following pods:

   .. code-block:: text

      pod/vllm-deployment-router-8666bf6464-v97v8 condition met
      NAME                                          READY   STATUS    RESTARTS   AGE   IP                NODE                       NOMINATED NODE   READINESS GATES
      kuberay-operator-f89ddb644-858bw              1/1     Running   0          12h   192.168.165.203   insudevmachine             <none>           <none>
      vllm-deployment-router-8666bf6464-v97v8       1/1     Running   0          12h   192.168.165.206   insudevmachine             <none>           <none>
      vllm-distilgpt2-raycluster-head-wvqj5         1/1     Running   0          12h   192.168.190.20    instance-20250503-060921   <none>           <none>
      vllm-distilgpt2-raycluster-ray-worker-fdvnh   1/1     Running   0          12h   192.168.165.207   insudevmachine             <none>           <none>

   - In this example, the production stack is deployed in a Kubernetes environment consisting of two nodes, each equipped with two GPUs.

   - The Ray head and worker nodes are scheduled on separate nodes. A total of four GPUs are utilized, with each node contributing two GPUs.

   - The vllm-deployment-router pod functions as the request router, directing incoming traffic to the appropriate model-serving pod.

   - The vllm-distilgpt2-raycluster-head pod is responsible for running the primary vLLM command.

   - The vllm-distilgpt2-raycluster-ray-worker-* pods serve the model and handle inference requests.

2. Verify the service is exposed correctly:

   .. code-block:: bash

      kubectl get services

   Expected output:

   Ensure there are services for both the serving engine and the router:

   .. code-block:: text

      NAME                                  TYPE        CLUSTER-IP       EXTERNAL-IP   PORT(S)             AGE
      kuberay-operator                      ClusterIP   10.97.0.153      <none>        8080/TCP            13h
      kubernetes                            ClusterIP   10.96.0.1        <none>        443/TCP             13h
      vllm-distilgpt2-engine-service        ClusterIP   10.106.237.111   <none>        80/TCP              12h
      vllm-distilgpt2-raycluster-head-svc   ClusterIP   None             <none>        8000/TCP,8080/TCP   12h
      vllm-router-service                   ClusterIP   10.97.229.184    <none>        80/TCP              12h

   - The ``vllm-*-engine-service`` exposes the head node of the ray cluster.
   - The ``vllm-*-router-service`` handles routing and load balancing across model-serving pods.

3. Test the health endpoint:

   To verify that the service is operational, execute the following commands:

   .. code-block:: bash

      kubectl port-forward svc/vllm-router-service 30080:80
      curl http://localhost:30080/v1/models

   **Note:** Port forwarding must be performed from a separate shell session. If the deployment is configured correctly, you should receive a response similar to the following:

   .. code-block:: text

      {
          "object": "list",
          "data": [
              {
                  "id": "distilbert/distilgpt2",
                  "object": "model",
                  "created": 1747465656,
                  "owned_by": "vllm",
                  "root": null
              }
          ]
      }

   You may also perform a basic inference test to validate that pipeline parallelism is functioning as expected. Use the following curl command:

   .. code-block:: bash

      curl -X POST http://localhost:30080/v1/completions \
       -H "Content-Type: application/json" \
       -d '{
         "model": "distilbert/distilgpt2",
         "prompt": "Once upon a time,",
         "max_tokens": 10
       }'

   A successful response should resemble the following output:

   .. code-block:: text

      {
          "id": "cmpl-92c4ceef0f1c42c9bba10da8306bf86c",
          "object": "text_completion",
          "created": 1747465724,
          "model": "distilbert/distilgpt2",
          "choices": [
              {
                  "index": 0,
                  "text": "? Huh, are you all red?\n\n",
                  "logprobs": null,
                  "finish_reason": "length",
                  "stop_reason": null,
                  "prompt_logprobs": null
              }
          ],
          "usage": {
              "prompt_tokens": 5,
              "total_tokens": 15,
              "completion_tokens": 10,
              "prompt_tokens_details": null
          }
      }

   You can also monitor GPU usage for each Ray head and worker pod:

   .. code-block:: text

      kubectl exec -it vllm-distilgpt2-raycluster-head-wvqj5 -- /bin/bash
      root@vllm-distilgpt2-raycluster-head-wvqj5:/vllm-workspace# nvidia-smi
      Sat May 17 00:10:48 2025
      +-----------------------------------------------------------------------------------------+
      | NVIDIA-SMI 550.90.07              Driver Version: 550.90.07      CUDA Version: 12.4     |
      |-----------------------------------------+------------------------+----------------------+
      | GPU  Name                 Persistence-M | Bus-Id          Disp.A | Volatile Uncorr. ECC |
      | Fan  Temp   Perf          Pwr:Usage/Cap |           Memory-Usage | GPU-Util  Compute M. |
      |                                         |                        |               MIG M. |
      |=========================================+========================+======================|
      |   0  NVIDIA L4                      Off |   00000000:00:03.0 Off |                    0 |
      | N/A   76C    P0             35W /   72W |   20313MiB /  23034MiB |      0%      Default |
      |                                         |                        |                  N/A |
      +-----------------------------------------+------------------------+----------------------+
      |   1  NVIDIA L4                      Off |   00000000:00:04.0 Off |                    0 |
      | N/A   70C    P0             33W /   72W |   20305MiB /  23034MiB |      0%      Default |
      |                                         |                        |                  N/A |
      +-----------------------------------------+------------------------+----------------------+

      +-----------------------------------------------------------------------------------------+
      | Processes:                                                                              |
      |  GPU   GI   CI        PID   Type   Process name                              GPU Memory |
      |        ID   ID                                                               Usage      |
      |=========================================================================================|
      |    0   N/A  N/A         8      C   /usr/bin/python3                                0MiB |
      |    1   N/A  N/A      1082      C   ray::RayWorkerWrapper                           0MiB |
      +-----------------------------------------------------------------------------------------+

      ###########################################################################################

      kubectl exec -it vllm-distilgpt2-raycluster-ray-worker-fdvnh -- /bin/bash
      Defaulted container "vllm-ray-worker" out of: vllm-ray-worker, wait-gcs-ready (init)
      root@vllm-distilgpt2-raycluster-ray-worker-fdvnh:/vllm-workspace# nvidia-smi
      Sat May 17 00:12:06 2025
      +-----------------------------------------------------------------------------------------+
      | NVIDIA-SMI 550.90.07              Driver Version: 550.90.07      CUDA Version: 12.4     |
      |-----------------------------------------+------------------------+----------------------+
      | GPU  Name                 Persistence-M | Bus-Id          Disp.A | Volatile Uncorr. ECC |
      | Fan  Temp   Perf          Pwr:Usage/Cap |           Memory-Usage | GPU-Util  Compute M. |
      |                                         |                        |               MIG M. |
      |=========================================+========================+======================|
      |   0  NVIDIA L4                      Off |   00000000:00:03.0 Off |                    0 |
      | N/A   76C    P0             40W /   72W |   20065MiB /  23034MiB |      0%      Default |
      |                                         |                        |                  N/A |
      +-----------------------------------------+------------------------+----------------------+
      |   1  NVIDIA L4                      Off |   00000000:00:04.0 Off |                    0 |
      | N/A   72C    P0             38W /   72W |   20063MiB /  23034MiB |      0%      Default |
      |                                         |                        |                  N/A |
      +-----------------------------------------+------------------------+----------------------+

      +-----------------------------------------------------------------------------------------+
      | Processes:                                                                              |
      |  GPU   GI   CI        PID   Type   Process name                              GPU Memory |
      |        ID   ID                                                               Usage      |
      |=========================================================================================|
      |    0   N/A  N/A       243      C   ray::RayWorkerWrapper                           0MiB |
      |    1   N/A  N/A       244      C   ray::RayWorkerWrapper                           0MiB |
      +-----------------------------------------------------------------------------------------+

Conclusion
----------

In this tutorial, you configured and deployed the vLLM serving engine with support for pipeline parallelism across multiple GPUs within a multi-node Kubernetes environment using KubeRay. Additionally, you learned how to verify the deployment and monitor the associated pods to ensure proper operation. For further customization and configuration options, please consult the ``values.yaml`` file and the Helm chart documentation.

To deploy both a Ray cluster and standard Kubernetes deployments using a single Helm release, please refer to the example configuration file available at `tutorials/assets/values-15-b-minimal-pipeline-parallel-example-multiple-modelspec.yaml <https://github.com/vllm-project/production-stack/blob/main/tutorials/assets/values-15-b-minimal-pipeline-parallel-example-multiple-modelspec.yaml>`_.
