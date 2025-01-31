# Tutorial: Setting Up a Kubernetes Environment with GPUs on Your GPU Server

## Introduction

This tutorial guides you through the process of setting up a Kubernetes environment on a GPU-enabled server. We will install and configure `kubectl`, `helm`, and `minikube`, ensuring GPU compatibility for workloads requiring accelerated computing. By the end of this tutorial, you will have a fully functional Kubernetes environment ready for deploy the vLLM Production Stack.

## Table of Contents

- [Introduction](#introduction)
- [Table of Contents](#table-of-contents)
- [Prerequisites](#prerequisites)
- [Steps](#steps)
  - [Step 1: Installing kubectl](#step-1-installing-kubectl)
  - [Step 2: Installing Helm](#step-2-installing-helm)
  - [Step 3: Installing Minikube with GPU Support](#step-3-installing-minikube-with-gpu-support)
  - [Step 4: Verifying GPU Configuration](#step-4-verifying-gpu-configuration)

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

## Steps

### Step 1: Installing kubectl

1. Clone the repository and navigate to the `utils/` folder:

   ```bash
   git clone https://github.com/vllm-project/production-stack.git
   cd production-stack/utils
   ```

2. Execute the script `install-kubectl.sh`:

   ```bash
   bash install-kubectl.sh
   ```

3. **Explanation:**
   This script downloads the latest version of `kubectl`, the Kubernetes command-line tool, and places it in your PATH for easy execution.

4. **Expected Output:**
   - Confirmation that `kubectl` was downloaded and installed.
   - Verification message using:

     ```bash
     kubectl version --client
     ```

   Example output:

   ```plaintext
   Client Version: v1.32.1
   ```

### Step 2: Installing Helm

1. Execute the script `install-helm.sh`:

   ```bash
   bash install-helm.sh
   ```

2. **Explanation:**
   - Downloads and installs Helm, a package manager for Kubernetes.
   - Places the Helm binary in your PATH.

3. **Expected Output:**
   - Successful installation of Helm.
   - Verification message using:

     ```bash
     helm version
     ```

   Example output:

   ```plaintext
   version.BuildInfo{Version:"v3.17.0", GitCommit:"301108edc7ac2a8ba79e4ebf5701b0b6ce6a31e4", GitTreeState:"clean", GoVersion:"go1.23.4"}
   ```

### Step 3: Installing Minikube with GPU Support

1. Execute the script `install-minikube-cluster.sh`:

   ```bash
   bash install-minikube-cluster.sh
   ```

2. **Explanation:**
   - Installs Minikube if not already installed.
   - Configures the system to support GPU workloads by enabling the NVIDIA Container Toolkit and starting Minikube with GPU support.
   - Installs the NVIDIA `gpu-operator` chart to manage GPU resources within the cluster.

3. **Expected Output:**
   If everything goes smoothly, you should see the example output like following:

   ```plaintext
   😄  minikube v1.35.0 on Ubuntu 22.04 (kvm/amd64)
   ❗  minikube skips various validations when --force is supplied; this may lead to unexpected behavior
   ✨  Using the docker driver based on user configuration
   ......
   ......
   🏄  Done! kubectl is now configured to use "minikube" cluster and "default" namespace by default
   "nvidia" has been added to your repositories
   Hang tight while we grab the latest from your chart repositories...
   ......
   ......
   NAME: gpu-operator-1737507918
   LAST DEPLOYED: Wed Jan 22 01:05:21 2025
   NAMESPACE: gpu-operator
   STATUS: deployed
   REVISION: 1
   TEST SUITE: None
   ```

4. Some troubleshooting tips for installing gpu-operator:

   If gpu-operator fails to start because of the common seen “too many open files” issue for minikube (and [kind](https://kind.sigs.k8s.io/)), then a quick fix below may be helpful.

   The issue can be observed by one or more gpu-operator pods in `CrashLoopBackOff` status, and be confirmed by checking their logs. For example,

   ```console
   $ sudo kubectl -n gpu-operator logs daemonset/nvidia-device-plugin-daemonset -c nvidia-device-plugin
   IS_HOST_DRIVER=true
   NVIDIA_DRIVER_ROOT=/
   DRIVER_ROOT_CTR_PATH=/host
   NVIDIA_DEV_ROOT=/
   DEV_ROOT_CTR_PATH=/host
   Starting nvidia-device-plugin
   I0131 19:35:42.895845       1 main.go:235] "Starting NVIDIA Device Plugin" version=<
      d475b2cf
      commit: d475b2cfcf12b983a4975d4fc59d91af432cf28e
   >
   I0131 19:35:42.895917       1 main.go:238] Starting FS watcher for /var/lib/kubelet/device-plugins
   E0131 19:35:42.895933       1 main.go:173] failed to create FS watcher for /var/lib/kubelet/device-plugins/: too many open files
   ```

   The fix is [well documented](https://kind.sigs.k8s.io/docs/user/known-issues#pod-errors-due-to-too-many-open-files) by kind, it also works for minikube.

### Step 4: Verifying GPU Configuration

1. Ensure Minikube is running:

   ```bash
   sudo minikube status
   ```

   Expected output:

   ```plaintext
   minikube
   type: Control Plane
   host: Running
   kubelet: Running
   apiserver: Running
   kubeconfig: Configured
   ```

2. Verify GPU access within Kubernetes:

   ```bash
   sudo kubectl describe nodes | grep -i gpu
   ```

   Expected output:

   ```plaintext
     nvidia.com/gpu: 1
     ... (plus many lines related to gpu information)
   ```

3. Deploy a test GPU workload:

   ```bash
   sudo kubectl run gpu-test --image=nvidia/cuda:12.2.0-runtime-ubuntu22.04 --restart=Never -- nvidia-smi
   ```

    Wait for kubernetes to download and create the pod and then check logs to confirm GPU usage:

   ```bash
   sudo kubectl logs gpu-test
   ```

   You should see the nvidia-smi output from the terminal

## Conclusion

By following this tutorial, you have successfully set up a Kubernetes environment with GPU support on your server. You are now ready to deploy and test vLLM Production Stack on Kubernetes. For further configuration and workload-specific setups, consult the official documentation for `kubectl`, `helm`, and `minikube`.

What's next:

- [01-minimal-helm-installation](https://github.com/vllm-project/production-stack/blob/main/tutorials/01-minimal-helm-installation.md)
