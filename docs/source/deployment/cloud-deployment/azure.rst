.. _azure:

Azure Kubernetes Service
========================

Introduction
------------
This script automatically configures an AKS LLM inference cluster.
Make sure your ``Azure CLI`` is installed, logged in, and the region is properly configured.
You must have the following dependencies installed:

- ``az`` (Azure Command-Line Interface)
- ``kubectl`` (Kubernetes command-line tool)
- ``helm`` (Kubernetes package manager)

Additionally, ensure that the following ``Azure`` services are set up:

- ``Resource Groups`` for managing resources
- ``AKS`` cluster with proper networking configuration
- ``Azure Files`` or ``Azure Managed Disks`` for persistent storage


Steps to Follow
---------------

1. Deploy AKS vLLM Stack
~~~~~~~~~~~~~~~~~~~~~~~~

1.1 Modify the Configuration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Before running the deployment, ensure that the configuration file ``production_stack_specification.yaml`` is properly set up.
You need to configure:

- ``servingEngineSpec``: Define the model repository, resource requests, and storage settings.
- ``routerSpec``: Set up routing resource limits and requests.
- ``Persistent Storage``: If using ``Azure Files``, ensure that the persistent volume configuration matches your storage needs.

Modify these fields as needed to match your cluster requirements.

1.2 Execute the Deployment Script
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Run the deployment script by replacing ``RESOURCE_GROUP`` and ``YAML_FILE_PATH`` with the actual values:

.. code-block:: bash

    bash entry_point.sh setup RESOURCE_GROUP YAML_FILE_PATH

After executing the script, Kubernetes will start deploying the ``vLLM`` inference stack.
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


3. Persistent Storage Considerations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
If using ``Azure Files`` or ``Azure Managed Disks`` for storage, keep in mind:

- ``Azure Files`` must be mounted to the ``AKS`` cluster as a persistent volume.
- The storage account must be in the same region as the ``AKS`` cluster.
- The ``AKS`` node pool should have the appropriate permissions to access ``Azure Files``.
- Ensure that the ``RBAC`` policies are correctly set up for ``Azure CSI`` driver operation.

If you need to manually delete storage resources, you can do so via the ``Azure Portal`` or using ``Azure CLI`` commands.


4. Uninstall
~~~~~~~~~~~~

To remove the deployed ``vLLM`` stack and clean up resources, run:

.. code-block:: bash

    bash entry_point.sh cleanup RESOURCE_GROUP

You may also need to manually delete the resource group and clean up any remaining resources via the Azure Portal.


5. Troubleshooting
~~~~~~~~~~~~~~~~~~~

If you encounter issues, refer to the following solutions:

- **Pods stuck in** ``Pending`` **state:** Check available resources and ensure that the cluster has enough nodes:

  .. code-block:: bash

      kubectl describe nodes

- **Pods in** ``CrashLoopBackOff`` **state:** Inspect logs to find the issue:

  .. code-block:: bash

      kubectl logs <POD_NAME>

- **Cannot connect to** ``AKS`` **cluster:** Ensure that your ``Azure CLI`` is properly configured:

  .. code-block:: bash

      az aks get-credentials --resource-group <RESOURCE_GROUP> --name <CLUSTER_NAME>

Following these steps should help ensure a successful deployment.
