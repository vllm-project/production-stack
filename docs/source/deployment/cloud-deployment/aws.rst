.. _aws:

Amazon Web Services
====================

Introduction
------------
This script automatically configures an EKS LLM inference cluster.
Make sure your ``AWS CLI (v2)`` is installed, logged in, and the region is properly configured.
You must have the following dependencies installed:

- ``awscli`` (Amazon Web Services CLI)
- ``eksctl`` (for managing Kubernetes clusters on AWS EKS)
- ``kubectl`` (Kubernetes command-line tool)
- ``helm`` (Kubernetes package manager)

Additionally, ensure that the following ``AWS`` services are set up:

- ``IAM`` roles and policies for ``EKS`` and ``EFS``
- ``VPC`` with properly configured subnets
- ``EKS`` cluster networking and security groups


Steps to Follow
---------------

1. Deploy EKS vLLM Stack
~~~~~~~~~~~~~~~~~~~~~~~~

1.1 Modify the Configuration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Before running the deployment, ensure that the configuration file ``production_stack_specification.yaml`` is properly set up.
You need to configure:

- ``servingEngineSpec``: Define the model repository, resource requests, and storage settings.
- ``routerSpec``: Set up routing resource limits and requests.
- ``Persistent Storage``: If using ``AWS EFS``, ensure that the persistent volume configuration matches your storage needs.

Modify these fields as needed to match your cluster requirements.

1.2 Execute the Deployment Script
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Run the deployment script by replacing ``YOUR_AWSREGION`` and ``YAML_FILE_PATH`` with the actual values:

.. code-block:: bash

    bash entry_point.sh YOUR_AWSREGION YAML_FILE_PATH

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
If using ``AWS EFS`` for storage, keep in mind:

- ``EFS`` must be created within the same ``VPC`` as the ``EKS`` cluster.
- The security group for ``EFS`` must allow ``NFS`` traffic (``port 2049``) from the ``EKS`` node group.
- The ``EFS`` storage should be properly mounted as a PersistentVolume for long-term model storage.
- Ensure that the ``IAM`` policies are correctly set up to allow ``EFS CSI`` driver operation.

If you need to manually delete ``EFS`` resources, you can do so via the ``AWS Console`` or using ``AWS CLI`` commands.


4. Uninstall
~~~~~~~~~~~~

To remove the deployed ``vLLM`` stack and clean up resources, run:

.. code-block:: bash

    bash clean_up.sh production-stack YOUR_AWSREGION

You may also need to manually delete the VPC and clean up the CloudFormation stack in the AWS Console if they were created as part of the deployment.


5. Troubleshooting
~~~~~~~~~~~~~~~~~~~

If you encounter issues, refer to the following solutions:

- **Pods stuck in** ``Pending`` **state:** Check available resources and ensure that the cluster has enough nodes:

  .. code-block:: bash

      kubectl describe nodes

- **Pods in** ``CrashLoopBackOff`` **state:** Inspect logs to find the issue:

  .. code-block:: bash

      kubectl logs <POD_NAME>

- **Cannot connect to** ``EKS`` **cluster:** Ensure that your ``AWS CLI`` is properly configured:

  .. code-block:: bash

      aws eks update-kubeconfig --name production-stack --region <YOUR_AWSREGION>

Following these steps should help ensure a successful deployment.
