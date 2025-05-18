# Tutorial: Setting Up a Kubernetes Environment with GPUs on Your GPU Server

## Introduction

This tutorial provides a comprehensive guide to setting up a Kubernetes environment across multiple GPU-enabled servers. It covers the installation and configuration of `kubeadm`, `kubectl`, and `helm`, with a focus on ensuring GPU compatibility for workloads that require accelerated computing. By the end of this tutorial, you will have a fully operational multi-node Kubernetes cluster prepared for deploying the vLLM Production Stack.

## Table of Contents

- [Introduction](#introduction)
- [Table of Contents](#table-of-contents)
- [Prerequisites](#prerequisites)
- [Steps](#steps)
  - [Step 1: Installing kubeadm on each node](#step-1-installing-kubeadm-on-each-node)
  - [Step 2: Installing container runtime on each node](#step-2-installing-container-runtime-on-each-node)
  - [Step 3: Setting up a control plane node](#step-3-setting-up-a-control-plane-node)
  - [Step 4: Setting and joining a worker node](#step-4-setting-and-joining-a-worker-node)
  - [Step 5: Installing container network interface](#step-5-installing-container-network-interface)
  - [Step 6: Installing nvidia device plugin](#step-6-installing-nvidia-device-plugin)

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

4. **Tested Environment:**
   - This guide was tested on a Debian 11 (Bullseye) operating system with 24 CPUs, 100 GiB of RAM, and 300 GiB of disk space. Please note that certain configurations or settings may vary or not function as expected on different systems, depending on your specific environment.

## Steps

### Step 1: Installing kubeadm on each node

1. Access to a bare-metal server that will serve as the control plane node.

2. Clone the repository and navigate to the [`utils/`](../utils/) folder:

   ```bash
   git clone https://github.com/vllm-project/production-stack.git
   cd production-stack/utils
   ```

3. Execute the script [`install-kubeadm.sh`](../utils/install-kubeadm.sh):

   ```bash
   bash install-kubeadm.sh
   ```

4. **Expected Output:**
   - Confirmation that `kubeadm` was downloaded and installed.
   - Verification message using:

     ```bash
     kubeadm version
     ```

   Example output:

   ```plaintext
   kubeadm version: &version.Info{Major:"1", Minor:"32", GitVersion:"v1.32.4", GitCommit:"59526cd4867447956156ae3a602fcbac10a2c335", GitTreeState:"clean", BuildDate:"2025-04-22T16:02:27Z", GoVersion:"go1.23.6", Compiler:"gc", Platform:"linux/amd64"}
   ```

5. **Explanation:**
   This script downloads version 1.32 of [`kubeadm`](https://v1-32.docs.kubernetes.io/docs/setup/production-environment/tools/kubeadm/install-kubeadm/), the Kubernetes command-line tool for cluster management, along with kubectl and kubelet, on the current node.

6. Repeat steps 1 to 3 on your other bare-metal server, which will serve as a worker node.

### Step 2: Installing container runtime on each node

1. Access to a bare-metal server that will serve as the control plane node.

2. Execute the script [`install-cri-o.sh`](../utils/install-helm.sh):

   ```bash
   bash install-cri-o.sh
   ```

3. **Expected Output:**
   - Successful installation of cri-o runtime.
   - Verification message using:

     ```bash
     sudo systemctl status crio
     ```

   Example output:

   ```plaintext
   ● crio.service - Container Runtime Interface for OCI (CRI-O)
      Loaded: loaded (/lib/systemd/system/crio.service; enabled; vendor preset: enabled)
      Active: active (running) since Fri 2025-05-16 16:32:31 UTC; 20h ago
         Docs: https://github.com/cri-o/cri-o
      Main PID: 2332175 (crio)
         Tasks: 61
      Memory: 14.4G
         CPU: 17min 55.486s
      CGroup: /system.slice/crio.service
   ```

4. **Explanation:**
   - Downloads, installs and configures v1.32 version of cri-o container runtime for your Kubernetes cluster.

5. **Explanation:**
   This script downloads v1.32 version of [`cri-0`](https://github.com/cri-o/packaging/blob/main/README.md#distributions-using-deb-packages), one of container runtimes for Kubernetes for managing pods on your cluster.

6. Repeat steps 1 to 2 on your other bare-metal server, which will serve as a worker node.

### Step 3: Setting up a control plane node

1. Access to a bare-metal server that will serve as the control plane node.

2. Execute the following command and wait for it to complete:

   ```bash
   # Look for a line starting with "default via"
   # For example: default via 10.128.0.1 dev ens5
   ip route show

   # Or get your network interface's ip address using the following command:
   export K8S_NET_IP=$(ip addr show dev $(ip route show | awk '/^default/ {print $5}') | awk '/inet / {print $2}' | cut -d/ -f1)
   echo "K8S_NET_IP=${K8S_NET_IP}"

   # On one of the nodes designated to become a control plane node, execute the following command:
   sudo kubeadm init \
      --cri-socket=unix:///var/run/crio/crio.sock \
      --apiserver-advertise-address=${K8S_NET_IP} \
      --pod-network-cidr=192.168.0.0/16
   ```

   Example output:

   ```plaintext
   # Your Kubernetes control-plane has initialized successfully!

   # To start using your cluster, you need to run the following as a regular user:

   #   mkdir -p $HOME/.kube
   #   sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
   #   sudo chown $(id -u):$(id -g) $HOME/.kube/config

   # Alternatively, if you are the root user, you can run:

   #   export KUBECONFIG=/etc/kubernetes/admin.conf

   # You should now deploy a pod network to the cluster.
   # Run "kubectl apply -f [podnetwork].yaml" with one of the options listed at:
   #   https://kubernetes.io/docs/concepts/cluster-administration/addons/

   # Then you can join any number of worker nodes by running the following on each as root:

   # kubeadm join <YOUR_CONTROL_PLANE_NODE_IP> --token <YOUR_GENERATED_TOKEN> \
   #         --discovery-token-ca-cert-hash <YOUR_GENERATED_CA_CERT_HASH>
   ```

   Perform following command to set your kube config:

   ```bash
   mkdir -p $HOME/.kube
   sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
   sudo chown $(id -u):$(id -g) $HOME/.kube/config
   ```

   If your control plane node is equipped with GPUs and you want GPU-enabled pods to be scheduled on it, you must remove the default taint from the node:

   ```bash
   kubectl taint node instance-20250503-060921 node-role.kubernetes.io/control-plane-
   ```

3. **Expected Output:**
   - Successful initialization of control plane node.
   - Verification message using:

     ```bash
     kubectl get nodes -o wide
     ```

   Example output:

   ```plaintext
   NAME                       STATUS   ROLES           AGE   VERSION   INTERNAL-IP     EXTERNAL-IP   OS-IMAGE                         KERNEL-VERSION          CONTAINER-RUNTIME
   instance-20250503-060921   Ready    control-plane   20h   v1.32.4   10.xxx.x.xx     <none>        Debian GNU/Linux 11 (bullseye)   5.10.0-33-cloud-amd64   cri-o://1.32.4
   ```

   Refer to [`official kubeadm documentation`](https://v1-32.docs.kubernetes.io/docs/setup/production-environment/tools/kubeadm/create-cluster-kubeadm/) for more information.

### Step 4: Setting and joining a worker node

1. Access to a bare-metal server that will serve as the worker node.

2. Execute the following command and wait for it to complete:

   ```bash
   # You got following output from previous control node initialization:

   # --------------------------------------------------------------------------------
   # Your Kubernetes control-plane has initialized successfully!
   #
   # ...
   #
   # Then you can join any number of worker nodes by running the following on each as root:
   #
   # kubeadm join <YOUR_CONTROL_PLANE_NODE_IP> --token <YOUR_GENERATED_TOKEN> \
   #         --discovery-token-ca-cert-hash sha256:<YOUR_GENERATED_CA_CERT_HASH>
   # --------------------------------------------------------------------------------

   # Execute the following command on your worker node:
   sudo kubeadm join <YOUR_CONTROL_PLANE_NODE_IP>:6443 --token <YOUR_GENERATED_TOKEN> \
            --discovery-token-ca-cert-hash sha256:<YOUR_GENERATED_CA_CERT_HASH> \
            --cri-socket=unix:///var/run/crio/crio.sock
   ```

   If you lost above information, you can get the token and hash by running following command on your CONTROL PLANE node::

   ```bash
   # To get <YOUR_CONTROL_PLANE_NODE_IP>:
   export K8S_NET_IP=$(ip addr show dev $(ip route show | awk '/^default/ {print $5}') | awk '/inet / {print $2}' | cut -d/ -f1)
   echo "K8S_NET_IP=${K8S_NET_IP}"

   # To get <YOUR_CONTROL_PLANE_NODE_IP>:
   sudo kubeadm token create

   # To get <YOUR_GENERATED_CA_CERT_HASH>:
   openssl x509 -pubkey -in /etc/kubernetes/pki/ca.crt | \
   openssl rsa -pubin -outform der 2>/dev/null | \
   sha256sum | awk '{print $1}'
   ```

   Example output:

   ```plaintext
   sudo kubeadm join <YOUR_CONTROL_PLANE_NODE_IP>:6443 --token <YOUR_CONTROL_PLANE_NODE_IP> --discovery-token-ca-cert-hash sha256:<YOUR_GENERATED_CA_CERT_HASH> --cri-socket=unix:///var/run/crio/crio.sock
   [preflight] Running pre-flight checks
   [preflight] Reading configuration from the "kubeadm-config" ConfigMap in namespace "kube-system"...
   [preflight] Use 'kubeadm init phase upload-config --config your-config.yaml' to re-upload it.
   [kubelet-start] Writing kubelet configuration to file "/var/lib/kubelet/config.yaml"
   [kubelet-start] Writing kubelet environment file with flags to file "/var/lib/kubelet/kubeadm-flags.env"
   [kubelet-start] Starting the kubelet
   [kubelet-check] Waiting for a healthy kubelet at http://127.0.0.1:10248/healthz. This can take up to 4m0s
   [kubelet-check] The kubelet is healthy after 500.795239ms
   [kubelet-start] Waiting for the kubelet to perform the TLS Bootstrap

   This node has joined the cluster:
   * Certificate signing request was sent to apiserver and a response was received.
   * The Kubelet was informed of the new secure connection details.

   Run 'kubectl get nodes' on the control-plane to see this node join the cluster.
   ```

   Copy kube config file from your control plane node to current worker node (with ssh or scp):

   ```bash
   mkdir -p $HOME/.kube
   scp YOUR_SSH_ACCOUNT:$HOME/.kube/config $HOME/.kube/config
   sudo chown $(id -u):$(id -g) $HOME/.kube/config
   ```

3. **Expected Output:**
   - Successful initialization of worker node.
   - Verification message using:

     ```bash
     kubectl get nodes -o wide
     ```

   Example output:

   ```plaintext
   NAME                       STATUS   ROLES           AGE   VERSION   INTERNAL-IP     EXTERNAL-IP   OS-IMAGE                         KERNEL-VERSION          CONTAINER-RUNTIME
   instance-20250503-060921   Ready    control-plane   20h   v1.32.4   10.xxx.x.xxx     <none>        Debian GNU/Linux 11 (bullseye)   5.10.0-33-cloud-amd64   cri-o://1.32.4
   insudevmachine             Ready    <none>          14m   v1.32.4   10.yyy.y.yyy   <none>        Debian GNU/Linux 11 (bullseye)   5.10.0-33-cloud-amd64   cri-o://1.32.4
   ```

   Refer to [`official kubeadm documentation`](https://kubernetes.io/docs/reference/setup-tools/kubeadm/kubeadm-join/) for more information.

### Step 5: Installing container network interface

1. Access to a bare-metal server that will serve as the control plane node.

2. Clone the repository and navigate to the [`utils/`](../utils/) folder:

   ```bash
   git clone https://github.com/vllm-project/production-stack.git
   cd production-stack/utils
   ```

3. Execute the script [`install-calico.sh`](../utils/install-calico.sh):

   ```bash
   bash install-calico.sh
   ```

4. **Expected Output:**
   - Confirmation that the `Tigera` operator and its associated custom resources have been successfully installed.
   - Verification message using:

     ```bash
     kubectl get pods -o wide
     ```

   Example output:

   ```plaintext
   NAMESPACE          NAME                                                          READY   STATUS      RESTARTS      AGE   IP                NODE                       NOMINATED NODE   READINESS
   GATES
   calico-apiserver   calico-apiserver-cccf4bb9f-8lbc7                              1/1     Running     0             21h   192.168.190.7     instance-20250503-060921   <none>           <none>
   calico-apiserver   calico-apiserver-cccf4bb9f-knn9c                              1/1     Running     0             21h   192.168.190.4     instance-20250503-060921   <none>           <none>
   calico-system      calico-kube-controllers-56dfdbb787-c24gd                      1/1     Running     0             21h   192.168.190.2     instance-20250503-060921   <none>           <none>
   calico-system      calico-node-dtbcq                                             1/1     Running     0             21h   10.xxx.xxx.xxx       instance-20250503-060921   <none>           <none>
   calico-system      calico-node-jptsp                                             1/1     Running     0             33m   10.xxx.xxx.xxx      insudevmachine             <none>           <none>
   calico-system      calico-typha-b7d75bc58-h6vrb                                  1/1     Running     0             37m   10.xxx.xxx.xxx        instance-20250503-060921   <none>           <none>
   calico-system      csi-node-driver-884sn                                         2/2     Running     0             26m   192.168.165.193   insudevmachine             <none>           <none>
   calico-system      csi-node-driver-bb7dl                                         2/2     Running     0             21h   192.168.190.1     instance-20250503-060921   <none>           <none>
   calico-system      goldmane-7b5b4cd5d9-6bk5p                                     1/1     Running     0             21h   192.168.190.6     instance-20250503-060921   <none>           <none>
   calico-system      whisker-5dbf545674-hnkpz                                      2/2     Running     0             21h   192.168.190.8     instance-20250503-060921   <none>           <none>
   ...
   kube-system        coredns-668d6bf9bc-5hvx7                                      1/1     Running     0             21h   192.168.190.3     instance-20250503-060921   <none>           <none>
   kube-system        coredns-668d6bf9bc-wb7qq                                      1/1     Running     0             21h   192.168.190.5     instance-20250503-060921   <none>           <none>
   ```

   Ensure that the status of each node is marked as “Ready” and that the CoreDNS pods are running:

   ```bash
   kubectl get nodes

   # NAME                       STATUS   ROLES           AGE   VERSION
   # instance-20250503-060921   Ready    control-plane   21h   v1.32.4
   # insudevmachine             Ready    <none>          37m   v1.32.4

   kubectl get pods -n kube-system | grep -i coredns

   # coredns-668d6bf9bc-5hvx7                           1/1     Running   0          21h
   # coredns-668d6bf9bc-wb7qq                           1/1     Running   0          21h
   ```

5. **Explanation:**
   This script downloads version 3.30.0 of [`calico`](https://docs.tigera.io/calico/latest/getting-started/kubernetes/quickstart), a container network interface (CNI) plugin for Kubernetes clusters.

### Step 6: Installing nvidia device plugin

1. Access to a bare-metal server that will serve as the control plane node.

2. Clone the repository and navigate to the [`utils/`](../utils/) folder:

   ```bash
   git clone https://github.com/vllm-project/production-stack.git
   cd production-stack/utils
   ```

3. Execute the script [`init-nvidia-gpu-setup-k8s.sh`](../utils/init-nvidia-gpu-setup-k8s.sh):

   ```bash
   bash init-nvidia-gpu-setup-k8s.sh
   ```

4. **Explanation:**
   - Configures the system to support GPU workloads by enabling the NVIDIA Container Toolkit and starting Minikube with GPU support.
   - Installs the NVIDIA `gpu-operator` chart to manage GPU resources within the cluster.

5. **Expected Output:**
   If everything goes smoothly, you should see the example output like following:

   ```plaintext
   ...
   NAME: gpu-operator-1737507918
   LAST DEPLOYED: Wed Jan 22 01:05:21 2025
   NAMESPACE: gpu-operator
   STATUS: deployed
   REVISION: 1
   TEST SUITE: None
   ```

6. Some troubleshooting tips for installing gpu-operator:

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

## Conclusion

By completing this tutorial, you have successfully established a multi-node Kubernetes environment with GPU support on your servers. You are now prepared to deploy and test the vLLM Production Stack within this Kubernetes cluster. For additional configuration and workload-specific guidance, please refer to the official documentation for `kubectl`, `helm`, and `minikube`.

What's next:

- [00-b-install-kuberay-operator](https://github.com/vllm-project/production-stack/blob/main/tutorials/00-b-install-kuberay-operator.md)
