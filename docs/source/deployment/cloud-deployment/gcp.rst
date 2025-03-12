.. _gcp:

Google Cloud Platform
=====================

Introduction
------------
This script automatically configures a ``GKE LLM`` inference cluster.
Make sure your ``GCP CLI`` is set up, logged in, and the region is properly configured.
You must have the following dependencies installed:

- ``gcloud`` (Google Cloud CLI)
- ``kubectl`` (Kubernetes command-line tool)
- ``helm`` (Kubernetes package manager)

Ensure that all the required tools are installed before proceeding.
Additionally, ensure that the following ``GCP`` ``APIs`` are enabled:

- ``Kubernetes Engine API``
- ``Cloud Resource Manager API``
- ``IAM API``
- ``Compute Engine API``

To enable these ``APIs``, run:

.. code-block:: bash

    gcloud services enable container.googleapis.com cloudresourcemanager.googleapis.com iam.googleapis.com compute.googleapis.com


Steps to Follow
---------------

1. Deploy GKE vLLM Stack
~~~~~~~~~~~~~~~~~~~~~~~~

1.1 Modify the Configuration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Before running the deployment, ensure that the configuration file ``production_stack_specification.yaml`` is properly set up.
You need to configure:

- ``servingEngineSpec``: Define the model repository, resource requests, and storage settings.
- ``routerSpec``: Set up routing resource limits and requests.

Modify these fields as needed to match your cluster requirements.

1.2 Execute the Deployment Script
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Run the deployment script by replacing ``YAML_FILE_PATH`` with the actual configuration file path:

.. code-block:: bash

    sudo bash entry_point.sh YAML_FILE_PATH

After executing the script, ``Kubernetes`` will start deploying the ``vLLM`` inference stack.
You can monitor the status of the deployment.


2. Validate Installation
~~~~~~~~~~~~~~~~~~~~~~~~

2.1 Monitor Deployment Status
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
To check whether the pods for ``vLLM`` deployment are up and running, use:

.. code-block:: bash

    kubectl get pods

Expected output:

.. code-block:: bash

    NAME                                            READY   STATUS    RESTARTS   AGE
    vllm-deployment-router-69b7f9748d-xrkvn         1/1     Running   0          75s
    vllm-opt125m-deployment-vllm-696c998c6f-mvhg4   1/1     Running   0          75s

.. note::

    It may take some time for the pods to reach the ``Running`` state, depending on cluster setup and image download speed.

2.2 Inspect Pod Logs
^^^^^^^^^^^^^^^^^^^^
If a pod is not transitioning to ``Running``, use the following command to inspect logs:

.. code-block:: bash

    kubectl logs -f <POD_NAME>

To get more detailed information about the pod, run:

.. code-block:: bash

    kubectl describe pod <POD_NAME>


3. Uninstall
~~~~~~~~~~~~

To remove the deployed ``vLLM`` stack and clean up resources, run:

.. code-block:: bash

    bash clean_up.sh production-stack

This command will remove all ``Kubernetes`` resources associated with the ``vLLM`` deployment.


4. Troubleshooting
~~~~~~~~~~~~~~~~~~~

If you encounter issues, refer to the following solutions:

- **Pods stuck in** ``Pending`` **state:** Check available resources and ensure that the cluster has enough nodes:

  .. code-block:: bash

      kubectl describe nodes

- **Pods in** ``CrashLoopBackOff`` **state:** Inspect logs to find the issue:

  .. code-block:: bash

      kubectl logs <POD_NAME>

- **Cannot connect to** ``GKE`` **cluster: Ensure that your** ``gcloud`` **CLI is properly configured:**

  .. code-block:: bash

      gcloud container clusters get-credentials vllm-gke-cluster --region <REGION>

Following these steps should help ensure a successful deployment.
