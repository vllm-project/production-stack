# Tutorial: Loading Model Weights from Persistent Volume

## Introduction

In this tutorial, you will learn how to load a model from a Persistent Volume (PV) in Kubernetes to optimize deployment performance. The steps include creating a PV, matching it using `pvcMatchLabels`, and deploying the Helm chart to utilize the PV. You will also verify the setup by examining the contents and measuring performance improvements.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Step 1: Creating a Persistent Volume](#step-1-creating-a-persistent-volume)
3. [Step 2: Deploying with Helm Using the PV](#step-2-deploying-with-helm-using-the-pv)
4. [Step 3: Verifying the Deployment](#step-3-verifying-the-deployment)

## Prerequisites

- A running Kubernetes cluster with GPU support.
- Completion of previous tutorials:
  - [00-install-kubernetes-env.md](00-install-kubernetes-env.md)
  - [01-minimal-helm-installation.md](01-minimal-helm-installation.md)
  - [02-basic-vllm-config.md](02-basic-vllm-config.md)
- Basic understanding of Kubernetes PV and PVC concepts.

## Step 1: Creating a Persistent Volume

1. Locate the persistent Volume manifest file at `tutorials/assets/pv-03.yaml`) with the following content:

   ```yaml
   apiVersion: v1
   kind: PersistentVolume
   metadata:
     name: test-vllm-pv
     labels:
       model: "llama3-pv"
   spec:
     capacity:
       storage: 50Gi
     accessModes:
       - ReadWriteOnce
     persistentVolumeReclaimPolicy: Retain
     storageClassName: standard
     hostPath:
       path: /data/llama3
   ```

   > **Note:** You can change the path specified in the `hostPath` field to any valid directory on your Kubernetes node.

2. Apply the manifest:

   ```bash
   sudo kubectl apply -f tutorials/assets/pv-03.yaml
   ```

3. Verify the PV is created:

   ```bash
   sudo kubectl get pv
   ```

   Expected output:

   ```plaintext
   NAME           CAPACITY   ACCESS MODES   RECLAIM POLICY   STATUS      CLAIM   STORAGECLASS   AGE
   test-vllm-pv   50Gi       RWO            Retain           Available           standard       2m
   ```

## Step 2: Deploying with Helm Using the PV

1. Locate the example values file at `tutorials/assets/values-03-match-pv.yaml` with the following content:

   ```yaml
   servingEngineSpec:
     modelSpec:
     - name: "llama3"
       repository: "vllm/vllm-openai"
       tag: "latest"
       modelURL: "meta-llama/Llama-3.1-8B-Instruct"
       replicaCount: 1

       requestCPU: 10
       requestMemory: "16Gi"
       requestGPU: 1

       pvcStorage: "50Gi"
       pvcMatchLabels:
         model: "llama3-pv"

       vllmConfig:
         maxModelLen: 4096

       hf_token: <YOUR HF TOKEN>
   ```

   > **Explanation:** The `pvcMatchLabels` field specifies the labels to match an existing Persistent Volume. In this example, it ensures that the deployment uses the PV with the label `model: "llama3-pv"`. This provides a way to link a specific PV to your application.

   > **Note:** Make sure to replace `<YOUR_HF_TOKEN>` with your actual Hugging Face token in the yaml.

2. Deploy the Helm chart:

   ```bash
   helm install vllm vllm/vllm-stack -f tutorials/assets/values-03-match-pv.yaml
   ```

3. Verify the deployment:

   ```bash
   sudo kubectl get pods
   ```

   Expected output:

   ```plaintext
   NAME                                             READY   STATUS    RESTARTS   AGE
   vllm-deployment-router-xxxx-xxxx             1/1     Running   0          1m
   vllm-llama3-deployment-vllm-xxxx-xxxx        1/1     Running   0          1m
   ```

## Step 3: Verifying the Deployment

1. Check the contents of the host directory:

   - If using a standard Kubernetes node:

     ```bash
     sudo ls /data/llama3
     ```

   - If using Minikube, access the Minikube VM and check the path:

     ```bash
     sudo minikube ssh
     ls /data/llama3/hub
     ```

   Expected output:

   You should see the model files loaded into the directory:

   ```plaintext
   models--meta-llama--Llama-3.1-8B-Instruct  version.txt
   ```

2. Uninstall and reinstall the deployment to observe faster startup:

   ```bash
   sudo helm uninstall vllm
   sudo kubectl delete -f tutorials/assets/pv-03.yaml && sudo kubectl apply -f tutorials/assets/pv-03.yaml
   helm install vllm vllm/vllm-stack -f tutorials/assets/values-03-match-pv.yaml
   ```

### Explanation

- During the second installation, the serving engine starts faster because the model files are already loaded into the Persistent Volume.

## Conclusion

In this tutorial, you learned how to utilize a Persistent Volume to store model weights for a vLLM serving engine. This approach optimizes deployment performance and demonstrates the benefits of Kubernetes storage resources. Continue exploring advanced configurations in future tutorials.
