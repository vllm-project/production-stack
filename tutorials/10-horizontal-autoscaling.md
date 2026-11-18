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
  - [5. Set Up Horizontal Pod Autoscaling](#5-set-up-horizontal-pod-autoscaling)
  - [6. Test the Autoscaling](#6-test-the-autoscaling)
  - [7. Cleanup](#7-cleanup)

## Prerequisites

1. A local clone of this repository
2. A Kubernetes cluster that can schedule two GPU replicas on the same node, since the example shares a `ReadWriteOnce` volume
3. `kubectl`, `helm`, `jq`, and Python 3 with the `openai` package installed
4. Basic understanding of Kubernetes and metrics

Run the commands from the repository root. The vLLM deployment and HPA use the `default` namespace.

## Steps

### 1. Install the Production Stack with a single Pod

Follow the instructions in [02-basic-vllm-config.md](02-basic-vllm-config.md) to install the vLLM Production Stack with a single Pod.

### 2. Deploy the Observability Stack

The observability stack is based on kube-prometheus-stack and includes Prometheus, Grafana, and other monitoring tools.

```bash
bash observability/install.sh
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
kubectl apply -f tutorials/assets/hpa-10.yaml
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

### 6. Test the Autoscaling

Monitor the HPA status:

```bash
kubectl --namespace default get hpa vllm-hpa -w
```

The output should show the HPA status and the current number of replicas.

```plaintext
NAME       REFERENCE                                     TARGETS   MINPODS   MAXPODS   REPLICAS   AGE
vllm-hpa   Deployment/vllm-llama3-deployment-vllm   0/1       1         2         1          34s
```

In a second terminal, forward port 30080 to the router Service created by the basic configuration. The router distributes requests across the ready engine Pods as the deployment scales.

```bash
kubectl --namespace default port-forward svc/vllm-router-service 30080:80
```

Once the port forward is listening, run the [load generator](assets/example-10-load-generator.py) from the repository root in another terminal. Use a shorter prompt to leave room for generation within the configured 4,096-token limit.

```bash
python3 tutorials/assets/example-10-load-generator.py --num-requests 100 --prompt-len 1000
```

Watch the HPA status. If the waiting-request metric stays above the target, the HPA can request a second replica.

### 7. Cleanup

Stop the port forward and the HPA watch with Ctrl+C. Then remove the HPA and the observability stack.

```bash
kubectl delete -f tutorials/assets/hpa-10.yaml
bash observability/uninstall.sh
```

## Upcoming Features for HPA in vLLM Production Stack

- Support CRD based HPA configuration

## Additional Resources

- [Kubernetes HPA Documentation](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)
- [Prometheus Adapter Documentation](https://github.com/kubernetes-sigs/prometheus-adapter)
- [vLLM Production Stack Repository](https://github.com/vllm-project/production-stack)
