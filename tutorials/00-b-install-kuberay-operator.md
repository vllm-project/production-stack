# Tutorial: Setting Up a Kuberay Operator on Your Kubernetes Environment

## Introduction

This tutorial provides a step-by-step guide to installing and configuring the KubeRay operator within a Kubernetes environment. We will use the helm chart to set up kuberay, enabling distributed inference with vLLM. By the end of this tutorial, you will have a fully operational KubeRay operator ready to support the deployment of the vLLM Production Stack.

## Table of Contents

- [Introduction](#introduction)
- [Table of Contents](#table-of-contents)
- [Prerequisites](#prerequisites)
- [Steps](#steps)
  - [Step 1: Install the KubeRay Operator Using Helm](#step-1-install-the-kuberay-operator-using-helm)
  - [Step 2: Verify the KubeRay Configuration](#step-2-verify-the-kuberay-configuration)

## Prerequisites

Before you begin, ensure the following:

1. **GPU Server Requirements:**
   - A server with a GPU and drivers properly installed (e.g., NVIDIA drivers).
   - [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) installed for GPU workloads.

2. **Access and Permissions:**
   - Root or administrative access to the server.
   - Internet connectivity to download required packages and tools.

3. **Environment Setup:**
   - A Linux-based operating system (e.g., Ubuntu 20.04 or later).
   - Basic understanding of Linux shell commands.

4. **Kubernetes Installation:**
   - To quickly and easily set up a single-node Kubernetes environment, you may install Minikube by following the instructions provided in[`00-install-kubernetes-env.md`](00-install-kubernetes-env.md).
   - For setting up a multi-node cluster or a more generalized Kubernetes environment, you may install Kubernetes from scratch using Kubeadm. This involves configuring the container runtime and container network interface (CNI), as outlined in [`00-a-install-multinode-kubernetes-env.md`](00-a-install-multinode-kubernetes-env.md)
   - If you already have a running Kubernetes cluster, you may skip this step.

5. **Kuberay Concept Review:**
   - Review the [`official KubeRay documentation`](https://docs.ray.io/en/latest/cluster/kubernetes/index.html) for additional context and best practices.

## Steps

### Step 1: Install the KubeRay Operator Using Helm

1. Add the KubeRay Helm repository:

   ```bash
   helm repo add kuberay https://ray-project.github.io/kuberay-helm/
   helm repo update
   ```

2. Install the Custom Resource Definitions (CRDs) and the KubeRay operator (version 1.2.0) in the default namespace:

   ```bash
   helm install kuberay-operator kuberay/kuberay-operator --version 1.2.0
   ```

3. **Explanation:**
   This step deploys the stable KubeRay operator in your Kubernetes cluster. The operator is essential for managing Ray clusters and enables you to scale multiple vLLM instances for distributed inference workloads.

### Step 2: Verify the KubeRay Configuration

1. **Check the Operator Pod Status:**
   - Ensure that the KubeRay operator pod is running in the default namespace:

     ```bash
     kubectl get pods
     ```

2. **Expected Output:**
   Example output:

   ```plaintext
   NAME                                          READY   STATUS    RESTARTS   AGE
   kuberay-operator-975995b7d-75jqd              1/1     Running   0          25h
   ```

## Conclusion

You have now successfully installed and verified the KubeRay operator in your Kubernetes environment. This setup lays the foundation for deploying and managing the vLLM Production Stack for distributed inference or training workloads.

For advanced configurations and workload-specific tuning, refer to the official documentation for kuberay, kubectl, helm, and minikube.

What's next:

- [15-basic-pipeline-parallel](https://github.com/vllm-project/production-stack/blob/main/tutorials/15-basic-pipeline-parallel.md)
