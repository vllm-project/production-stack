# Tutorial: Scale Your vLLM Deployments Using the vLLM Production Stack

## Introduction

This tutorial guides you through setting up horizontal pod autoscaling (HPA) for vLLM deployments using Prometheus metrics. By the end of this tutorial, you'll have a vLLM deployment that automatically scales based on the number of waiting requests in the queue.

## Table of Contents

- [Introduction](#introduction)
- [Table of Contents](#table-of-contents)
- [Prerequisites](#prerequisites)
- [Steps](#steps)
  - [1. Install the Production Stack with a single Pod](#1-install-the-production-stack-with-a-single-pod)
  - [2. Deploy the Observability Stack](#2-deploy-the-observability-stack)
  - [3. Configure Prometheus Adapter](#3-configure-prometheus-adapter)
  - [4. Verify Metrics Export](#4-verify-metrics-export)
  - [5. Test the Autoscaling](#5-test-the-autoscaling)
  - [6. Cleanup](#6-cleanup)

## Prerequisites

1. A working vLLM deployment on Kubernetes (follow [01-minimal-helm-installation](01-minimal-helm-installation.md))
2. Kubernetes environment with 2 GPUs
3. `kubectl` and `helm` installed
4. Basic understanding of Kubernetes and metrics

## Steps

### 1. Install the Production Stack with a single Pod

Follow the instructions in [02-basic-vllm-config.md](02-basic-vllm-config.md) to install the vLLM Production Stack with a single Pod.

### 2. Deploy the Observability Stack

The observability stack is based on kube-prometheus-stack and includes Prometheus, Grafana, and other monitoring tools.

```bash
# Navigate to the observability directory
cd production-stack/observability

# Install the observability stack
sudo bash install.sh
```

### 3. Configure Prometheus Adapter

The Prometheus Adapter is automatically configured during installation to export vLLM metrics. The key metric we'll use for autoscaling in this tutorial is `vllm_num_requests_waiting`.

You can learn more about the Prometheus Adapter in the [Prometheus Adapter README](https://github.com/prometheus-community/helm-charts/tree/main/charts/prometheus-adapter).

### 4. Verify Metrics Export

Check if the metrics are being exported correctly:

```bash
# Check if the metric is available
kubectl get --raw /apis/custom.metrics.k8s.io/v1beta1 | jq | grep vllm_num_requests_waiting -C 10

# Get the current value of the metric
kubectl get --raw /apis/custom.metrics.k8s.io/v1beta1/namespaces/default/metrics/vllm_num_requests_waiting | jq
```

Expected output should show the metric and its current value:

```json
{
  "items": [
    {
      "describedObject": {
        "kind": "Namespace",
        "name": "default",
        "apiVersion": "/v1"
      },
      "metricName": "vllm_num_requests_waiting",
      "value": "0"
    }
  ]
}
```

### 5. Set Up Horizontal Pod Autoscaling

Locate the file [assets/hpa-10.yaml](assets/hpa-10.yaml) with the following content:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: vllm-hpa
  namespace: default
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: vllm-llama3-deployment-vllm # Name of the deployment to scale
  minReplicas: 1
  maxReplicas: 2
  metrics:
  - type: Object
    object:
      metric:
        name: vllm_num_requests_waiting
      describedObject:
        apiVersion: v1
        kind: Namespace
        name: default   # The namespace where the metric is collected
      target:
        type: Value
        value: 1  # Scale up if the metric exceeds 1
```

Apply the HPA to your Kubernetes cluster:

```bash
kubectl apply -f assets/hpa-10.yaml
```

Explanation of the HPA configuration:

- `minReplicas`: The minimum number of replicas to scale down to
- `maxReplicas`: The maximum number of replicas to scale up to
- `metric`: The metric to scale on
- `target`: The target value of the metric

The above HPA will:

- Maintain between 1 and 2 replicas
- Scale up when there are more than 1 requests waiting in the queue
- Scale down when the queue length decreases

### 5. Test the Autoscaling

Monitor the HPA status:

```bash
kubectl get hpa vllm-hpa -w
```

The output should show the HPA status and the current number of replicas.

```plaintext
NAME       REFERENCE                                     TARGETS   MINPODS   MAXPODS   REPLICAS   AGE
vllm-hpa   Deployment/vllm-llama3-deployment-vllm   0/1       1         2         1          34s
```

We provide a load test script in [assets/example-10-load-generator.py](assets/example-10-load-generator.py) to test the autoscaling.

```bash
# In the production-stack/tutorials directory
kubectl port-forward svc/vllm-engine-service 30080:80 &
python3 assets/example-10-load-generator.py --num-requests 100 --prompt-len 10000
```

You should see the HPA scale up the number of replicas to 2 and there is a new vLLM pod created.

### 6. Cleanup

To remove the observability stack and HPA:

```bash
# Remove HPA
kubectl delete -f assets/hpa-10.yaml

# Uninstall observability stack (in the production-stack/tutorials directory)
cd ../observability # Go back to the observability directory
sudo bash uninstall.sh
```

## Upcoming Features for HPA in vLLM Production Stack

- Support CRD based HPA configuration

## Additional Resources

- [Kubernetes HPA Documentation](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)
- [Prometheus Adapter Documentation](https://github.com/kubernetes-sigs/prometheus-adapter)
- [vLLM Production Stack Repository](https://github.com/vllm-project/production-stack)
