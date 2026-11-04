# Tutorial: Loading Model Weights from Persistent Volumes

## Introduction

A Persistent Volume (PV) can be used with vLLM Production Stack in two different ways:

1. **Persist the Hugging Face cache:** vLLM downloads a model from Hugging Face on the first start and reuses the cached files on later starts.
2. **Serve a pre-downloaded model offline:** model files are placed in the PV before deployment, and vLLM starts directly from their local path without downloading them.

This tutorial demonstrates both workflows. In either workflow, the chart mounts the model volume at `/data` inside the serving-engine container.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Create a Persistent Volume](#create-a-persistent-volume)
3. [Workflow A: Persist the Hugging Face Cache](#workflow-a-persist-the-hugging-face-cache)
4. [Workflow B: Serve a Pre-Downloaded Model Offline](#workflow-b-serve-a-pre-downloaded-model-offline)
5. [Use an Existing Persistent Volume Claim](#use-an-existing-persistent-volume-claim)
6. [Troubleshooting](#troubleshooting)

## Prerequisites

- A running Kubernetes cluster with GPU support.
- Completion of the previous tutorials:
  - [Install Kubernetes Environment](00-install-kubernetes-env.md)
  - [Minimal Helm Installation](01-minimal-helm-installation.md)
  - [Basic vLLM Configuration](02-basic-vllm-config.md)
- Basic knowledge of Kubernetes PVs and Persistent Volume Claims (PVCs).
- For the offline workflow, a complete model directory in a format supported by vLLM. A Hugging Face-format model normally contains `config.json`, tokenizer files, and all referenced weight shards.

## Create a Persistent Volume

The example PV is defined in [`tutorials/assets/pv-03.yaml`](assets/pv-03.yaml):

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

Apply it and confirm that it is available:

```bash
kubectl apply -f tutorials/assets/pv-03.yaml
kubectl get pv test-vllm-pv
```

Expected status before Helm creates the matching PVC:

```text
NAME           CAPACITY   ACCESS MODES   RECLAIM POLICY   STATUS      STORAGECLASS
test-vllm-pv   50Gi       RWO            Retain           Available   standard
```

> [!WARNING]
> `hostPath` refers to one Kubernetes node. It is useful for a controlled single-node development example, but it is not shared storage. For production or multi-node deployments, use storage accessible from every eligible node, or constrain the serving pod to the node that contains the files.

## Workflow A: Persist the Hugging Face Cache

This workflow lets vLLM download the model on its first start. Because the chart sets `HF_HOME=/data` when model PVC storage is configured, the Hugging Face cache is written to the PV and reused by later pods.

### Deploy the online example

The existing values file [`tutorials/assets/values-03-match-pv.yaml`](assets/values-03-match-pv.yaml) selects the PV by label:

```yaml
servingEngineSpec:
  runtimeClassName: ""
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
    pvcAccessMode:
      - ReadWriteOnce
    pvcMatchLabels:
      model: "llama3-pv"

    vllmConfig:
      maxModelLen: 4096

    hf_token: <YOUR HF TOKEN>
```

Replace `<YOUR HF TOKEN>`, then install the chart:

```bash
helm install vllm vllm/vllm-stack \
  -f tutorials/assets/values-03-match-pv.yaml
```

Confirm that the generated PVC is bound to the example PV:

```bash
kubectl get pv test-vllm-pv
kubectl get pvc vllm-llama3-storage-claim
```

After the model is downloaded, the PV backing directory contains the Hugging Face cache. For the example `hostPath`, inspect it on the Kubernetes node:

```bash
sudo ls /data/llama3/hub
```

A later serving pod can reuse this cache instead of downloading every model file again.

## Workflow B: Serve a Pre-Downloaded Model Offline

This workflow starts vLLM directly from model files that already exist in the PV. It does not use a Hugging Face repository ID at startup.

### Understand the node path and container path

`modelURL` is evaluated **inside the serving-engine container**. It must not point to an unmounted path on the Kubernetes node.

The example PV root is `/data/llama3` on the node, while the chart mounts that root at `/data` in the container. Therefore these paths identify the same directory:

| Location | Model directory |
| --- | --- |
| Kubernetes node | `/data/llama3/Llama-3.1-8B-Instruct` |
| Serving container | `/data/Llama-3.1-8B-Instruct` |
| `modelURL` value | `/data/Llama-3.1-8B-Instruct` |

Populate the PV backing directory before installing the chart. Run the following on the node that owns the example `hostPath`, replacing the source path with your downloaded model directory:

```bash
sudo mkdir -p /data/llama3/Llama-3.1-8B-Instruct
sudo cp -a /path/to/downloaded/Llama-3.1-8B-Instruct/. \
  /data/llama3/Llama-3.1-8B-Instruct/
sudo chmod -R a+rX /data/llama3/Llama-3.1-8B-Instruct
test -f /data/llama3/Llama-3.1-8B-Instruct/config.json
```

For other storage providers, use the provider's supported method to populate the volume before deployment.

### Deploy the offline example

Use [`tutorials/assets/values-03-local-model.yaml`](assets/values-03-local-model.yaml):

```yaml
servingEngineSpec:
  runtimeClassName: ""
  modelSpec:
  - name: "llama3-local"
    repository: "vllm/vllm-openai"
    tag: "latest"
    modelURL: "/data/Llama-3.1-8B-Instruct"
    replicaCount: 1

    requestCPU: 10
    requestMemory: "16Gi"
    requestGPU: 1

    pvcStorage: "50Gi"
    pvcAccessMode:
      - ReadWriteOnce
    pvcMatchLabels:
      model: "llama3-pv"

    vllmConfig:
      maxModelLen: 4096

    env:
      - name: HF_HUB_OFFLINE
        value: "1"
      - name: TRANSFORMERS_OFFLINE
        value: "1"
```

The offline environment variables prevent an accidental network fallback. No `hf_token` is required when the PV already contains every required file.

Install the chart:

```bash
helm install vllm vllm/vllm-stack \
  -f tutorials/assets/values-03-local-model.yaml
```

Confirm that the PVC selected the expected PV:

```bash
kubectl get pv test-vllm-pv
kubectl get pvc vllm-llama3-local-storage-claim
```

Confirm that the exact path passed as `modelURL` and its metadata are visible in the container:

```bash
ENGINE_POD=$(kubectl get pods \
  -l model=llama3-local,helm-release-name=vllm \
  -o jsonpath='{.items[0].metadata.name}')

kubectl exec "$ENGINE_POD" -c vllm -- \
  test -f /data/Llama-3.1-8B-Instruct/config.json
kubectl exec "$ENGINE_POD" -c vllm -- \
  ls -la /data/Llama-3.1-8B-Instruct
```

Check the serving-engine logs. The vLLM command and loading messages should reference the local `/data/...` path:

```bash
kubectl logs "$ENGINE_POD" -c vllm
```

Finally, forward the router service and verify that the model is advertised:

```bash
kubectl port-forward service/vllm-router-service 8000:80
```

In another terminal:

```bash
curl -s http://localhost:8000/v1/models | jq
```

## Use an Existing Persistent Volume Claim

If the model is already stored in a PVC managed outside this chart, set `pvcExistingClaimName`. The chart mounts the existing claim at `/data` and does not create another PVC:

```yaml
servingEngineSpec:
  modelSpec:
  - name: "llama3-local"
    repository: "vllm/vllm-openai"
    tag: "latest"
    modelURL: "/data/Llama-3.1-8B-Instruct"

    # pvcStorage enables the model volume. It does not resize the existing PVC.
    pvcStorage: "50Gi"
    pvcExistingClaimName: "my-preloaded-model-pvc"

    env:
      - name: HF_HUB_OFFLINE
        value: "1"
      - name: TRANSFORMERS_OFFLINE
        value: "1"
```

The existing PVC must be in the same namespace as the Helm release. Its access mode and storage backend must also permit access from every node on which the serving pod can be scheduled.

## Troubleshooting

### `Invalid repository ID or local directory`

This error usually means `modelURL` is neither a valid repository ID nor a valid directory inside the container.

- Use the container path, such as `/data/Llama-3.1-8B-Instruct`, not the node path `/data/llama3/Llama-3.1-8B-Instruct`.
- Confirm that the directory exists in the `vllm` container.
- Confirm that `config.json` is directly inside the directory specified by `modelURL`.

### Files exist on the node but not in the container

Check that the PVC is bound to the intended PV:

```bash
kubectl get pv test-vllm-pv
kubectl get pvc vllm-llama3-local-storage-claim -o wide
kubectl describe pvc vllm-llama3-local-storage-claim
```

Also inspect the pod's volumes and mounts:

```bash
kubectl describe pod "$ENGINE_POD"
```

If the pod is running on a different node, a `hostPath` on the original node is not visible there. Use shared storage or constrain pod placement.

### The model is nested one directory deeper than expected

List the mounted directory:

```bash
kubectl exec "$ENGINE_POD" -c vllm -- find /data -maxdepth 3 -name config.json
```

Set `modelURL` to the directory that directly contains the correct `config.json`. For example, if the command prints `/data/models/Llama-3.1-8B-Instruct/config.json`, use:

```yaml
modelURL: "/data/models/Llama-3.1-8B-Instruct"
```

### The model directory is incomplete

A `config.json` file alone is not sufficient. Ensure the directory also contains the tokenizer assets, model weights, and every shard referenced by the model's index files. Re-run the original download or copy operation if files are missing.

### The serving pod cannot be inspected because it restarts

Read the previous container logs and inspect its volume configuration:

```bash
kubectl logs "$ENGINE_POD" -c vllm --previous
kubectl describe pod "$ENGINE_POD"
```

Local-path and missing-file errors near startup normally identify the path or file that needs correction.

## Conclusion

A PV can either persist vLLM's Hugging Face cache or hold a complete model that vLLM loads directly. For offline loading, populate the volume first, use the path as it appears inside the container, and verify that the exact `modelURL` directory contains all required model files.
