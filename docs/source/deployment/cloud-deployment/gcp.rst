.. _gcp:

Google Cloud Platform
=====================
Introduction
------------
This script automatically configures a GKE LLM inference cluster.
Make sure your GCP CLI is set up, logged in, and the region is properly configured.
You must have the following dependencies installed:

- `eksctl` (for managing Kubernetes clusters on AWS EKS)
- `kubectl` (Kubernetes command-line tool)
- `helm` (Kubernetes package manager)

Ensure that all the required tools are installed before proceeding.

Steps to Follow
---------------
1. Deploy GKE vLLM Stack
~~~~~~~~~~~~~~~~~~~~~~~~
1.1 Modify the Configuration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Modify the fields in the `production_stack_specification.yaml` file as per your requirements.

1.2 Execute the Deployment Script
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Run the deployment script by replacing `YAML_FILE_PATH` with the actual configuration file path:

.. code-block:: bash

    sudo bash entry_point.sh YAML_FILE_PATH

After executing the script, Kubernetes will start deploying the vLLM inference stack.
You can monitor the status of the deployment.


2. Validate Installation
~~~~~~~~~~~~~~~~~~~~~~~~

2.1 Monitor Deployment Status
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

To check whether the pods for vLLM deployment are up and running, use:

.. code-block:: bash

    sudo kubectl get pods

Expected output:

.. code-block:: console

    NAME                                            READY   STATUS    RESTARTS   AGE
    vllm-deployment-router-69b7f9748d-xrkvn         1/1     Running   0          75s
    vllm-opt125m-deployment-vllm-696c998c6f-mvhg4   1/1     Running   0          75s

.. note::

    It may take some time for the pods to reach the `Running` state, depending on cluster setup and image download speed.

3. Uninstall
~~~~~~~~~~~~

To remove the deployed vLLM stack and clean up resources, run:

.. code-block:: bash

    bash clean_up.sh production-stack

This command will remove all Kubernetes resources associated with the vLLM deployment.
