# Tutorial: Setting Up a Kubernetes Environment with GPUs on Your GPU Server

## Introduction

This tutorial guides you through the process of setting up a Kubernetes environment on a GPU-enabled server.
We will install and configure `helm` and `kind`, ensuring GPU compatibility for workloads. By the end of this tutorial,
you will have a fully functional Kubernetes environment ready to deploy the vLLM Production Stack. Note that kind uses
Docker containers as nodes, and pods are an abstraction of co-location and co-scheduling/resource sharing among actual
application containers run within such nodes.

## Table of Contents

- [Introduction](#introduction)
- [Table of Contents](#table-of-contents)
- [Prerequisites](#prerequisites)
- [Steps](#steps)
  - [Step 1: Installing kind](#step-1-installing-kind)
  - [Step 2: Installing Helm](#step-2-installing-helm)
  - [Step 3: Installing kind with GPU Support](#step-3-installing-kind-with-gpu-support)
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

### Step 1: Installing kind

1. Clone the repository and navigate to the [`utils/`](../utils/) folder:

   ```bash
   git clone https://github.com/vllm-project/production-stack.git
   cd production-stack/utils
   ```

2. Execute the script [`install-kind.sh`](../utils/install-kind.sh):

   ```bash
   bash install-kind.sh
   ```

3. **Explanation:**
   This script downloads the latest version of [`kind`](https://kind.sigs.k8s.io/), the Kubernetes in Docker tool, and
   places it in your PATH for easy execution.

4. **Expected Output:**
   - Confirmation that `kind` was downloaded and installed.
   - Verification message using:

     ```bash
     kind version
     ```

   Example output:

   ```plaintext
   kind v0.29.0 go1.24.2 linux/amd64
   ```

### Step 2: Installing Helm

1. Execute the script [`install-helm.sh`](../utils/install-helm.sh):

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

### Step 3: Installing kind with GPU Support

Before proceeding, ensure Docker runs without requiring sudo. To add your user to the docker group, run:

```bash
sudo usermod -aG docker $USER && newgrp docker
```

1. Execute the script [`install-kind-cluster.sh`](../utils/install-kind-cluster.sh):

   ```bash
   bash install-kind-cluster.sh
   ```

2. **Explanation:**
   - Sets NVIDIA container toolkit (nvidia-ctk) to be docker's default runtime
   - Creates a cluster titled `single-node-cluster` whose role is the control-plane and which has an NVIDIA mount
   - Adds NVIDIA helm repo and installs its `gpu-operator` helm chart to manage GPU resources within the cluster

3. **Expected Output:**
   If everything goes smoothly, you should see an output like the following:

   ```plaintext
    Restarting docker...
    Allowing volume mounts...
    Creating cluster "single-node-cluster" ...
    ✓ Ensuring node image (kindest/node:v1.27.3) 🖼
    ✓ Preparing nodes 📦
    ✓ Writing configuration 📜
    ✓ Starting control-plane 🕹️
    ✓ Installing CNI 🔌
    ✓ Installing StorageClass 💾
    Set kubectl context to "kind-single-node-cluster"
    You can now use your cluster with:

    kubectl cluster-info --context kind-single-node-cluster

    Have a nice day! 👋
    Adding nvidia helm repo and installing its gpu-operator helm chart...
    "nvidia" already exists with the same configuration, skipping
    Hang tight while we grab the latest from your chart repositories...
    ...Successfully got an update from the "vllm" chart repository
    ...Successfully got an update from the "nvidia" chart repository
    Update Complete. ⎈Happy Helming!⎈
    NAME: gpu-operator-1750621555
    LAST DEPLOYED: Sun Jun 22 19:45:58 2025
    NAMESPACE: gpu-operator
    STATUS: deployed
    REVISION: 1
    TEST SUITE: None
   ```

4. Some troubleshooting tips for installing gpu-operator:

   If gpu-operator fails to start because of the common seen “too many open files” issue for minikube (and [kind](https://kind.sigs.k8s.io/)), then a quick fix below may be helpful.

   The issue can be observed by one or more gpu-operator pods in `CrashLoopBackOff` status, and be confirmed by checking their logs. For example,

   ```console
   $ kubectl -n gpu-operator logs daemonset/nvidia-device-plugin-daemonset -c nvidia-device-plugin
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

1. Ensure kind is running:

   ```bash
   kind get clusters
   ```

   Expected output:

   ```plaintext
   single-node-cluster
   ```

2. Verify GPU access within Kubernetes:

   ```bash
   kubectl describe nodes | grep -i gpu
   ```

   Expected output:

   ```plaintext
     nvidia.com/gpu: 1
     ... (plus many lines related to gpu information)
   ```

3. Deploy a test GPU workload:

   ```bash
   kubectl run gpu-test --image=nvidia/cuda:12.2.0-runtime-ubuntu22.04 --restart=Never -- nvidia-smi
   ```

    Wait for kubernetes to download and create the pod and then check logs to confirm GPU usage:

   ```bash
   kubectl logs gpu-test
   ```

   You should see the nvidia-smi output from the terminal

## Conclusion

By following this tutorial, you have successfully set up a Kubernetes environment with GPU support on your server. You are now ready to deploy and test vLLM Production Stack on Kubernetes. For further configuration and workload-specific setups, consult the official documentation for `kubectl`, `helm`, and `kind`. To uninstall the cluster, enter:

```bash
kind delete cluster --name single-node-cluster
```

What's next:

- [01-minimal-helm-installation](https://github.com/vllm-project/production-stack/blob/main/tutorials/01-minimal-helm-installation.md)
