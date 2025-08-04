Autoscaling with KEDA
=====================

This tutorial shows you how to automatically scale a vLLM deployment using `KEDA <https://keda.sh/>`_ and Prometheus-based metrics. You'll configure KEDA to monitor queue length and dynamically adjust the number of replicas based on load.

Table of Contents
-----------------

- Prerequisites_
- Steps_

  - `1. Install the vLLM Production Stack`_
  - `2. Deploy the Observability Stack`_
  - `3. Install KEDA`_
  - `4. Verify Metric Export`_
  - `5. Configure the ScaledObject`_
  - `6. Test Autoscaling`_
  - `7. Cleanup`_

- `Additional Resources`_

Prerequisites
-------------

- A working vLLM deployment on Kubernetes (see :doc:`../getting_started/quickstart`)
- Access to a Kubernetes cluster with at least 2 GPUs
- ``kubectl`` and ``helm`` installed
- Basic understanding of Kubernetes and Prometheus metrics

Steps
-----

1. Install the vLLM Production Stack
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Install the production stack using a single pod by following the instructions in :doc:`../deployment/helm`.

2. Deploy the Observability Stack
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This stack includes Prometheus, Grafana, and necessary exporters.

.. code-block:: bash

   cd observability
   bash install.sh

3. Install KEDA
~~~~~~~~~~~~~~~

.. code-block:: bash

   kubectl create namespace keda
   helm repo add kedacore https://kedacore.github.io/charts
   helm repo update
   helm install keda kedacore/keda --namespace keda

4. Verify Metric Export
~~~~~~~~~~~~~~~~~~~~~~~

Check that Prometheus is scraping the queue length metric ``vllm:num_requests_waiting``.

.. code-block:: bash

   kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090

In a separate terminal:

.. code-block:: bash

   curl -G 'http://localhost:9090/api/v1/query' --data-urlencode 'query=vllm:num_requests_waiting'

Example output:

.. code-block:: json

   {
     "status": "success",
     "data": {
       "result": [
         {
           "metric": {
             "__name__": "vllm:num_requests_waiting",
             "pod": "vllm-llama3-deployment-vllm-xxxxx"
           },
           "value": [ 1749077215.034, "0" ]
         }
       ]
     }
   }

This means that at the given timestamp, there were 0 pending requests in the queue.

5. Configure the ScaledObject
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The following ``ScaledObject`` configuration is provided in ``tutorials/assets/values-19-keda.yaml``. Review its contents:

.. code-block:: yaml

   apiVersion: keda.sh/v1alpha1
   kind: ScaledObject
   metadata:
     name: vllm-scaledobject
     namespace: default
   spec:
     scaleTargetRef:
       name: vllm-llama3-deployment-vllm
     minReplicaCount: 1
     maxReplicaCount: 2
     pollingInterval: 15
     cooldownPeriod: 30
     triggers:
       - type: prometheus
         metadata:
           serverAddress: http://prometheus-operated.monitoring.svc:9090
           metricName: vllm:num_requests_waiting
           query: vllm:num_requests_waiting
           threshold: '5'

Apply the ScaledObject:

.. code-block:: bash

   cd ../tutorials
   kubectl apply -f assets/values-19-keda.yaml

This tells KEDA to:

- Monitor ``vllm:num_requests_waiting``
- Scale between 1 and 2 replicas
- Scale up when the queue exceeds 5 requests

6. Test Autoscaling
~~~~~~~~~~~~~~~~~~~

Watch the deployment:

.. code-block:: bash

   kubectl get hpa -n default -w

You should initially see:

.. code-block:: text

   NAME                         REFERENCE                                TARGETS     MINPODS   MAXPODS   REPLICAS
   keda-hpa-vllm-scaledobject   Deployment/vllm-llama3-deployment-vllm   0/5 (avg)   1         2         1

``TARGETS`` shows the current metric value vs. the target threshold.
``0/5 (avg)`` means the current value of ``vllm:num_requests_waiting`` is 0, and the threshold is 5.

Generate load:

.. code-block:: bash

   kubectl port-forward svc/vllm-router-service 30080:80

In a separate terminal:

.. code-block:: bash

   python3 assets/example-10-load-generator.py --num-requests 100 --prompt-len 3000

Within a few minutes, the ``REPLICAS`` value should increase to 2.

7. Cleanup
~~~~~~~~~~

To remove KEDA configuration and observability components:

.. code-block:: bash

   kubectl delete -f assets/values-19-keda.yaml
   helm uninstall keda -n keda
   kubectl delete namespace keda

   cd ../observability
   bash uninstall.sh

Additional Resources
--------------------

- `KEDA Documentation <https://keda.sh/docs/>`_
