Intelligent Semantic Routing
============================

This use case demonstrates how to integrate the vLLM Semantic Router with the vLLM Production Stack to create an intelligent Mixture-of-Models (MoM) system. The Semantic Router operates as an Envoy External Processor that semantically routes OpenAI API-compatible requests to the most suitable backend model using BERT-based/Decoder-Based LoRA classification, prompt guard, and semantic caching, improving both quality and cost efficiency.

What is vLLM Semantic Router?
------------------------------

The vLLM Semantic Router provides:

- **Auto-selection of models**: Routes math, creative writing, code, and general queries to the best-fit models
- **Security & privacy**: PII detection, prompt guard, and safe routing for sensitive prompts
- **Performance optimizations**: Semantic cache and better tool selection to cut latency and tokens
- **Architecture**: Tight Envoy ExtProc integration with dual Go and Rust implementations
- **Monitoring**: Console, Grafana dashboards, Prometheus metrics, and tracing for full visibility

Learn more: `vLLM Semantic Router <https://vllm-semantic-router.com>`_

Benefits of Integration
-----------------------

The vLLM Production Stack provides deployment capabilities that spin up vLLM servers with traffic routing to different models, service discovery and fault tolerance through the Kubernetes API, and support for round-robin, session-based, prefix-aware, KV-aware and disaggregated-prefill routing with LMCache native support.

The Semantic Router adds a system-intelligence layer that:

- Classifies each user request
- Selects the most suitable model from a pool
- Injects domain-specific system prompts
- Performs semantic caching
- Enforces enterprise-grade security checks such as PII and jailbreak detection

By combining these two systems, you obtain a unified inference stack where semantic routing ensures that each request is answered by the best possible model, while Production-Stack routing maximizes infrastructure and inference efficiency with rich metrics.

Table of Contents
-----------------

1. Prerequisites_
2. `Step 1: Deploy the vLLM Production Stack`_
3. `Step 2: Deploy vLLM Semantic Router`_
4. `Step 3: Test the Deployment`_
5. Troubleshooting_

Prerequisites
-------------

- kubectl
- Helm
- A Kubernetes cluster (kind, minikube, GKE, etc.)
- Completion of :doc:`../getting_started/prerequisite` and :doc:`../getting_started/quickstart`

Step 1: Deploy the vLLM Production Stack
-----------------------------------------

Deploy the vLLM Production Stack using the provided Helm values file:

.. code-block:: bash

   helm repo add vllm-production-stack https://vllm-project.github.io/production-stack
   helm install vllm-stack vllm-production-stack/vllm-stack -f https://github.com/vllm-project/production-stack/blob/main/tutorials/assets/values-23-SR.yaml

The sample values file configures:

- **Model**: Qwen/Qwen3-8B with 2 replicas
- **Router**: Round-robin routing logic with session key support
- **Resources**: 8 CPU, 16Gi memory, 1 GPU per instance

Identify the ClusterIP and port of your router Service:

.. code-block:: bash

   kubectl get svc vllm-router-service
   # Note the router service ClusterIP and port (e.g., 10.97.254.122:80)

Step 2: Deploy vLLM Semantic Router
------------------------------------

Follow the official `Install in Kubernetes <https://vllm-semantic-router.com/docs/installation/kubernetes>`_ guide with the updated configuration.

Update the semantic router config to include your vLLM router service as an endpoint. Edit ``deploy/kubernetes/config.yaml`` and set ``vllm_endpoints``:

.. code-block:: yaml

   vllm_endpoints:
     - name: "endpoint1"
       address: <YOUR ROUTER SERVICE CLUSTERIP>
       port: <YOUR ROUTER SERVICE PORT>
       weight: 1

Deploy the semantic router and required components:

.. code-block:: bash

   # Deploy vLLM Semantic Router manifests
   kubectl apply -k deploy/kubernetes/
   kubectl wait --for=condition=Available deployment/semantic-router \
     -n vllm-semantic-router-system --timeout=600s

   # Install Envoy Gateway
   helm upgrade -i eg oci://docker.io/envoyproxy/gateway-helm \
     --version v0.0.0-latest \
     --namespace envoy-gateway-system \
     --create-namespace
   kubectl wait --timeout=300s -n envoy-gateway-system \
     deployment/envoy-gateway --for=condition=Available

   # Install Envoy AI Gateway
   helm upgrade -i aieg oci://docker.io/envoyproxy/ai-gateway-helm \
     --version v0.0.0-latest \
     --namespace envoy-ai-gateway-system \
     --create-namespace
   kubectl wait --timeout=300s -n envoy-ai-gateway-system \
     deployment/ai-gateway-controller --for=condition=Available

   # Install Gateway API Inference Extension CRDs
   kubectl apply -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/v1.0.1/manifests.yaml
   kubectl get crd | grep inference

Apply AI Gateway configuration and create the inference pool:

.. code-block:: bash

   # Apply AI Gateway configuration
   kubectl apply -f deploy/kubernetes/ai-gateway/configuration

   # Restart controllers to pick up new config
   kubectl rollout restart -n envoy-gateway-system deployment/envoy-gateway
   kubectl rollout restart -n envoy-ai-gateway-system deployment/ai-gateway-controller
   kubectl wait --timeout=120s -n envoy-gateway-system deployment/envoy-gateway --for=condition=Available
   kubectl wait --timeout=120s -n envoy-ai-gateway-system deployment/ai-gateway-controller --for=condition=Available

   # Create inference pool
   kubectl apply -f deploy/kubernetes/ai-gateway/inference-pool
   sleep 30

   # Verify inference pool
   kubectl get inferencepool vllm-semantic-router -n vllm-semantic-router-system -o yaml

Step 3: Test the Deployment
----------------------------

Port-forward to the Envoy service:

.. code-block:: bash

   export GATEWAY_IP="localhost:8080"
   export ENVOY_SERVICE=$(kubectl get svc -n envoy-gateway-system \
     --selector=gateway.envoyproxy.io/owning-gateway-namespace=vllm-semantic-router-system,gateway.envoyproxy.io/owning-gateway-name=vllm-semantic-router \
     -o jsonpath='{.items[0].metadata.name}')
   kubectl port-forward -n envoy-gateway-system svc/$ENVOY_SERVICE 8080:80

Send a chat completions request:

.. code-block:: bash

   curl -i -X POST http://localhost:8080/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{
       "model": "MoM",
       "messages": [
         {"role": "user", "content": "What is the derivative of f(x) = x^3 + 2x^2 - 5x + 7?"}
       ]
     }'

The semantic router will analyze the request, identify it as a math query, and route it to the appropriate model through the vLLM Production Stack router.

Troubleshooting
---------------

- **Gateway not accessible**: Check the Gateway and Envoy service status
- **Inference pool not ready**: Run ``kubectl describe inferencepool`` and check controller logs
- **Semantic router not responding**: Check pod status and logs with ``kubectl logs -n vllm-semantic-router-system``
- **Error codes returned**: Check the production stack router logs with ``kubectl logs``

Conclusion
----------

In this use case, we've demonstrated how to:

1. Deploy vLLM Production Stack with a router service
2. Integrate vLLM Semantic Router with the production stack
3. Configure Envoy Gateway and AI Gateway for intelligent routing
4. Test the end-to-end semantic routing functionality

This integration provides a powerful combination of semantic intelligence and production-grade infrastructure, enabling efficient, secure, and intelligent model routing for diverse workloads.

.. note::

   **Preview Version**: This guide is based on the preview version of vLLM Semantic Router integration. The deployment steps, configuration options, and API interfaces may change in future releases as the feature evolves. Please refer to the latest documentation for updates.
