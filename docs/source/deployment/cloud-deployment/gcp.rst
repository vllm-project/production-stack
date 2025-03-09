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