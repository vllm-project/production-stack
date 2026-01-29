Autoscaling with KEDA
=====================

This tutorial shows you how to automatically scale a vLLM deployment using `KEDA <https://keda.sh/>`_ and Prometheus-based metrics. With the vLLM Production Stack Helm chart (v0.1.9+), KEDA autoscaling is integrated directly into the chart, allowing you to enable it through simple ``values.yaml`` configuration.

Table of Contents
-----------------

- Prerequisites_
- Steps_

  - `1. Deploy the Observability Stack`_
  - `2. Configure and Deploy vLLM`_
  - `3. Install KEDA`_
  - `4. Enable KEDA Autoscaling for vLLM`_
  - `5. Verify KEDA ScaledObject Creation`_
  - `6. Test Autoscaling`_
  - `7. Advanced Configuration`_
  - `8. Cleanup`_

- `Additional Resources`_

Prerequisites
-------------

- Access to a Kubernetes cluster with at least 2 GPUs
- ``kubectl`` and ``helm`` installed (v3.0+)
- Basic understanding of Kubernetes and Prometheus metrics

Steps
-----

1. Deploy the Observability Stack
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The observability stack (Prometheus, Grafana) is required for KEDA to query metrics.

.. code-block:: bash

   cd observability
   bash install.sh

Verify Prometheus is scraping the queue length metric ``vllm:num_requests_waiting``:

.. code-block:: bash

   kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090

In a separate terminal:

.. code-block:: bash

   curl -G 'http://localhost:9090/api/v1/query' --data-urlencode 'query=vllm:num_requests_waiting'

2. Configure and Deploy vLLM
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create a ``values.yaml`` file to deploy vLLM. Note that we'll enable KEDA autoscaling in a later step after KEDA is installed:

.. code-block:: yaml

   servingEngineSpec:
     enableEngine: true
     modelSpec:
       - name: "llama3"
         repository: "lmcache/vllm-openai"
         tag: "latest"
         modelURL: "meta-llama/Llama-3.1-8B-Instruct"
         replicaCount: 1
         requestCPU: 10
         requestMemory: "64Gi"
         requestGPU: 1

Deploy the chart:

.. code-block:: bash

   helm install vllm vllm/vllm-stack -f values.yaml

Wait for the vLLM deployment to be ready and verify that metrics are being exposed:

.. code-block:: bash

   kubectl wait --for=condition=ready pod -l model=llama3 --timeout=300s

Verify Prometheus is scraping the vLLM metrics:

.. code-block:: bash

   kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090

In a separate terminal:

.. code-block:: bash

   curl -G 'http://localhost:9090/api/v1/query' --data-urlencode 'query=vllm:num_requests_waiting'

3. Install KEDA
~~~~~~~~~~~~~~~

Now that vLLM is running and exposing metrics, install KEDA to enable autoscaling:

.. code-block:: bash

   kubectl create namespace keda
   helm repo add kedacore https://kedacore.github.io/charts
   helm repo update
   helm install keda kedacore/keda --namespace keda

Verify KEDA is running:

.. code-block:: bash

   kubectl get pods -n keda

4. Enable KEDA Autoscaling for vLLM
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Update your ``values.yaml`` file to enable KEDA autoscaling:

.. code-block:: yaml

   servingEngineSpec:
     enableEngine: true
     modelSpec:
       - name: "llama3"
         repository: "lmcache/vllm-openai"
         tag: "latest"
         modelURL: "meta-llama/Llama-3.1-8B-Instruct"
         replicaCount: 1
         requestCPU: 10
         requestMemory: "64Gi"
         requestGPU: 1

         # Enable KEDA autoscaling
         keda:
           enabled: true
           minReplicaCount: 1
           maxReplicaCount: 3
           pollingInterval: 15
           cooldownPeriod: 360
           triggers:
             - type: prometheus
               metadata:
                 serverAddress: http://prometheus-operated.monitoring.svc:9090
                 metricName: vllm:num_requests_waiting
                 query: vllm:num_requests_waiting
                 threshold: '5'

Upgrade the chart to enable KEDA autoscaling:

.. code-block:: bash

   helm upgrade vllm vllm/vllm-stack -f values.yaml

This configuration tells KEDA to:

- Monitor the ``vllm:num_requests_waiting`` metric from Prometheus
- Maintain between 1 and 3 replicas
- Scale up when the queue exceeds 5 pending requests
- Check metrics every 15 seconds
- Wait 360 seconds before scaling down after scaling up

5. Verify KEDA ScaledObject Creation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Check that the Helm chart created the ScaledObject resource:

.. code-block:: bash

   kubectl get scaledobjects

You should see:

.. code-block:: text

   NAME                        SCALETARGETKIND      SCALETARGETNAME                  MIN   MAX   TRIGGERS     AUTHENTICATION   READY   ACTIVE   FALLBACK   PAUSED    AGE
   vllm-llama3-scaledobject   apps/v1.Deployment   vllm-llama3-deployment-vllm      1     3     prometheus                    True    False    Unknown    Unknown   30s

View the created HPA:

.. code-block:: bash

   kubectl get hpa

Expected output:

.. code-block:: text

   NAME                            REFERENCE                                TARGETS     MINPODS   MAXPODS   REPLICAS
   keda-hpa-vllm-llama3-scaledobject   Deployment/vllm-llama3-deployment-vllm   0/5 (avg)   1         3         1

6. Test Autoscaling
~~~~~~~~~~~~~~~~~~~

Watch the HPA in real-time:

.. code-block:: bash

   kubectl get hpa -n default -w

Generate load to trigger autoscaling. Port-forward to the router service:

.. code-block:: bash

   kubectl port-forward svc/vllm-router-service 30080:80

In a separate terminal, run a load generator:

.. code-block:: bash

   python3 tutorials/assets/example-10-load-generator.py --num-requests 100 --prompt-len 3000

Within a few minutes, you should see the ``REPLICAS`` value increase as KEDA scales up to handle the load.

7. Advanced Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~

Scale-to-Zero
^^^^^^^^^^^^^

Enable scale-to-zero by setting ``minReplicaCount: 0`` and adding a traffic-based keepalive trigger:

.. code-block:: yaml

   keda:
     enabled: true
     minReplicaCount: 0  # Allow scaling to zero
     maxReplicaCount: 5
     triggers:
       # Queue-based scaling
       - type: prometheus
         metadata:
           serverAddress: http://prometheus-operated.monitoring.svc:9090
           metricName: vllm:num_requests_waiting
           query: vllm:num_requests_waiting
           threshold: '5'
       # Traffic-based keepalive (prevents scale-to-zero when traffic exists)
       - type: prometheus
         metadata:
           serverAddress: http://prometheus-operated.monitoring.svc:9090
           metricName: vllm:incoming_keepalive
           query: sum(rate(vllm:num_incoming_requests_total[1m]) > bool 0)
           threshold: "1"

Custom HPA Behavior
^^^^^^^^^^^^^^^^^^^

Control scaling behavior with custom HPA policies:

.. code-block:: yaml

   keda:
     enabled: true
     minReplicaCount: 1
     maxReplicaCount: 5
     advanced:
       horizontalPodAutoscalerConfig:
         behavior:
           scaleDown:
             stabilizationWindowSeconds: 300
             policies:
               - type: Percent
                 value: 50
                 periodSeconds: 60

Fallback Configuration
^^^^^^^^^^^^^^^^^^^^^^

Configure fallback behavior when metrics are unavailable:

.. code-block:: yaml

   keda:
     enabled: true
     fallback:
       failureThreshold: 3
       replicas: 2

For more configuration options, see the `Helm chart README <https://github.com/vllm-project/production-stack/blob/main/helm/README.md#keda-autoscaling-configuration>`_.

8. Cleanup
~~~~~~~~~~

To disable KEDA autoscaling, update your ``values.yaml`` to set ``keda.enabled: false`` and upgrade:

.. code-block:: bash

   helm upgrade vllm vllm/vllm-stack -f values.yaml

To completely remove KEDA from the cluster:

.. code-block:: bash

   helm uninstall keda -n keda
   kubectl delete namespace keda

To remove the observability stack:

.. code-block:: bash

   cd observability
   bash uninstall.sh

Additional Resources
--------------------

- `KEDA Documentation <https://keda.sh/docs/>`_
- `KEDA ScaledObject Specification <https://keda.sh/docs/2.18/reference/scaledobject-spec/>`_
- `Helm Chart KEDA Configuration <https://github.com/vllm-project/production-stack/blob/main/helm/README.md#keda-autoscaling-configuration>`_
