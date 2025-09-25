
.. _crd_deployment:

CRD Deployment
=======================================

Deploy minimal vLLM production stack on Kubernetes using Custom Resource Definitions (CRDs) and Custom Resources (CRs).

.. note::
   This deployment method is **recommended** for production environments as it provides better resource management, monitoring, and lifecycle management through Kubernetes operators.

Prerequisites
-------------

- **kubectl** version v1.11.3+
- Access to a Kubernetes v1.11.3+ cluster

Installation
------------

1. **Clone the repository**

   First, clone the vLLM production stack repository:

   .. code-block:: bash

      git clone https://github.com/vllm-project/production-stack.git

2. **Deploy the Operator**

   Deploy the production stack operator by running:

   .. code-block:: bash

      kubectl create -f operator/config/default.yaml

   This command achieves the following:

   - **Namespace Creation**: Creates a namespace called ``production-stack-system`` where the operator will run
   - **Custom Resource Definitions (CRDs)**: Defines 4 new custom resources that can be managed by this operator:

     - ``CacheServer``: For managing cache servers
     - ``LoraAdapter``: For managing LoRA adapters (used for model fine-tuning)
     - ``VLLMRouter``: For managing vLLM routing
     - ``VLLMRuntime``: For managing vLLM runtime instances

   - **RBAC (Role-Based Access Control)**: Creates various roles and role bindings to control access to these resources with permissions for:

     - Admin roles (full access)
     - Editor roles (create/update/delete)
     - Viewer roles (read-only)
     - Metrics and leader election

   - **Service Account**: Creates a service account ``production-stack-controller-manager`` for the operator
   - **Deployment**: Deploys the operator controller manager as a deployment with health checks, resource limits, and security settings using the image ``lmcache/production-stack-operator:latest``
   - **Service**: Creates a metrics service for monitoring the operator

3. **Verify the Operator Deployment**

   Check the status of the operator deployment:

   .. code-block:: bash

      kubectl get pods -n production-stack-system
      kubectl get deployment -n production-stack-system

   You should see output similar to:

   .. code-block:: bash

      NAME                                                              READY   STATUS    RESTARTS   AGE
      production-stack-production-stack-controller-manager-65b86brxm6   1/1     Running   0          21s

      NAME                                                   READY   UP-TO-DATE   AVAILABLE   AGE
      production-stack-production-stack-controller-manager   1/1     1            1           25s

Deploying vLLM Resources
------------------------

1. **Deploy vLLM Runtime**

   (Optional) If your model requires a Hugging Face token (like Llama-3.1-8B), create a secret:

   .. code-block:: bash

      kubectl create secret generic huggingface-token \
        --from-literal=token=<your-hf-token> \
        --namespace=default

   Deploy the vLLM runtime:

   .. code-block:: bash

      kubectl apply -f operator/config/samples/production-stack_v1alpha1_vllmruntime.yaml

   This creates a vLLM runtime instance in your Kubernetes cluster.

2. **Deploy vLLM Router**

   Start the vLLM router:

   .. code-block:: bash

      kubectl apply -f operator/config/samples/production-stack_v1alpha1_vllmrouter.yaml

   Verify both components are running:

   .. code-block:: bash

      kubectl get pods

   You should see:

   .. code-block:: bash

             NAME                                  READY   STATUS    RESTARTS   AGE
       vllmrouter-sample-6fc78b7f85-lt5n7    1/1     Running   0          3m31s
       vllmruntime-sample-7448f7547c-pdfml   1/1     Running   0          6m10s

3. **Troubleshooting Initial Deployment**

   If you encounter a ``RunContainerError``, check the logs:

   .. code-block:: bash

      kubectl get pods
      kubectl logs <pod-name>
      kubectl describe pod <pod-name>

Sample Configurations
---------------------

**VLLMRuntime Sample (production-stack_v1alpha1_vllmruntime.yaml)**

.. code-block:: yaml

   apiVersion: production-stack.vllm.ai/v1alpha1
   kind: VLLMRuntime
   metadata:
     labels:
       app.kubernetes.io/name: production-stack
       app.kubernetes.io/managed-by: kustomize
     name: vllmruntime-sample
   spec:
     # Model configuration
     model:
       modelURL: "meta-llama/Llama-3.1-8B"
       enableLoRA: false
       enableTool: false
       toolCallParser: ""
       maxModelLen: 4096
       dtype: "bfloat16"
       maxNumSeqs: 32
       # HuggingFace token secret (optional)
       hfTokenSecret:
         name: "huggingface-token"
       hfTokenName: "token"

     # vLLM server configuration
     vllmConfig:
       # vLLM specific configurations
       enableChunkedPrefill: false
       enablePrefixCaching: false
       tensorParallelSize: 1
       gpuMemoryUtilization: "0.8"
       maxLoras: 4
       extraArgs: ["--disable-log-requests"]
       v1: true
       port: 8000
       # Environment variables
       env:
         - name: HF_HOME
           value: "/data"

     # LM Cache configuration
     lmCacheConfig:
       enabled: true
       cpuOffloadingBufferSize: "15"
       diskOffloadingBufferSize: "0"
       remoteUrl: "lm://cacheserver-sample.default.svc.cluster.local:80"
       remoteSerde: "naive"

     # Deployment configuration
     deploymentConfig:
       # Resource requirements
       resources:
         cpu: "10"
         memory: "32Gi"
         gpu: "1"

       # Image configuration
       image:
         registry: "docker.io"
         name: "lmcache/vllm-openai:2025-05-27-v1"
         pullPolicy: "IfNotPresent"
         pullSecretName: ""

       # Number of replicas
       replicas: 1

       # Deployment strategy
       deploymentStrategy: "Recreate"

**VLLMRouter Sample (production-stack_v1alpha1_vllmrouter.yaml)**

.. code-block:: yaml

   apiVersion: production-stack.vllm.ai/v1alpha1
   kind: VLLMRouter
   metadata:
     labels:
       app.kubernetes.io/name: production-stack
       app.kubernetes.io/managed-by: kustomize
     name: vllmrouter-sample
   spec:
     # Enable the router deployment
     enableRouter: true

     # Number of router replicas
     replicas: 1

     # Service discovery method (k8s or static)
     serviceDiscovery: k8s

     # Label selector for vLLM runtime pods
     k8sLabelSelector: "app=vllmruntime-sample"

     # Routing strategy (roundrobin or session)
     routingLogic: roundrobin

     # Engine statistics collection interval
     engineScrapeInterval: 30

     # Request statistics window
     requestStatsWindow: 60

     # Container port for the router service
     port: 80

     # Service account name
     serviceAccountName: vllmrouter-sa

     # Image configuration
     image:
       registry: docker.io
       name: lmcache/lmstack-router
       pullPolicy: IfNotPresent

     # Resource requirements
     resources:
       cpu: "2"
       memory: "8Gi"

     # Environment variables
     env:
       - name: LOG_LEVEL
         value: "info"
       - name: METRICS_ENABLED
         value: "true"

     # Node selector for pod scheduling
     nodeSelectorTerms:
       - matchExpressions:
           - key: kubernetes.io/os
             operator: In
             values:
               - linux


Testing the Deployment
-----------------------

1. **Port Forward the Router**

   Expose the router service locally:

   .. code-block:: bash

      kubectl port-forward svc/vllmrouter-sample 30080:80 --address 0.0.0.0

2. **Test with a Simple Request**

   In a separate terminal, test the deployment with a curl command:

   .. code-block:: bash

      curl -X POST http://localhost:30080/v1/completions \
        -H "Content-Type: application/json" \
        -d '{
          "model": "meta-llama/Llama-3.1-8B",
          "prompt": "1 plus 1 equals to",
          "max_tokens": 100
        }'

   A successful response should look like:

   .. code-block:: json

      {
        "id": "cmpl-0c3a06af79df4cb2a5e6f8c3fb1f1215",
        "object": "text_completion",
        "created": 1750121964,
        "model": "meta-llama/Llama-3.1-8B",
        "choices": [
          {
            "index": 0,
            "text": " 2\nThis is a very simple equation...",
            "logprobs": null,
            "finish_reason": "length",
            "stop_reason": null,
            "prompt_logprobs": null
          }
        ],
        "usage": {
          "prompt_tokens": 8,
          "total_tokens": 108,
          "completion_tokens": 100,
          "prompt_tokens_details": null
        },
                 "kv_transfer_params": null
       }

Uninstall
---------

1. **Remove Custom Resources**

   .. code-block:: bash

      kubectl delete vllmrouter vllmrouter-sample
      kubectl delete vllmruntime vllmruntime-sample

2. **Remove Secrets (if created)**

   .. code-block:: bash

      kubectl delete secret huggingface-token --namespace=default

3. **Remove the Operator and CRDs**

   Remove the entire operator deployment and custom resource definitions:

   .. code-block:: bash

      kubectl delete -f operator/config/default.yaml

4. **Verify Cleanup**

   Confirm that all resources have been removed:

   .. code-block:: bash

      kubectl get namespace production-stack-system

      kubectl get crd | grep production-stack

      kubectl get pods --all-namespaces | grep -E "(vllmruntime|vllmrouter)"

   You should see no results from these commands, indicating successful cleanup.

Happy deploying! 🚀
