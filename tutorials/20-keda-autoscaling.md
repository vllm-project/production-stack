# Tutorial: Autoscale Your vLLM Deployment with KEDA

## Introduction

This tutorial shows you how to automatically scale a vLLM deployment using [KEDA](https://keda.sh/) and Prometheus-based metrics. You'll configure KEDA to monitor queue length and dynamically adjust the number of replicas based on load.

## Table of Contents

* [Introduction](#introduction)
* [Prerequisites](#prerequisites)
* [Steps](#steps)

  * [1. Install the vLLM Production Stack](#1-install-the-vllm-production-stack)
  * [2. Deploy the Observability Stack](#2-deploy-the-observability-stack)
  * [3. Install KEDA](#3-install-keda)
  * [4. Verify Metric Export](#4-verify-metric-export)
  * [5. Configure the ScaledObject](#5-configure-the-scaledobject)
  * [6. Test Autoscaling](#6-test-autoscaling)
  * [7. Cleanup](#7-cleanup)
* [Additional Resources](#additional-resources)

---

## Prerequisites

* A working vLLM deployment on Kubernetes (see [01-minimal-helm-installation](01-minimal-helm-installation.md))
* Access to a Kubernetes cluster with at least 2 GPUs
* `kubectl` and `helm` installed
* Basic understanding of Kubernetes and Prometheus metrics

---

## Steps

### 1. Install the vLLM Production Stack

Install the production stack using a single pod by following the instructions in [02-basic-vllm-config.md](02-basic-vllm-config.md).

---

### 2. Deploy the Observability Stack

This stack includes Prometheus, Grafana, and necessary exporters.

```bash
cd observability
bash install.sh
```

---

### 3. Install KEDA

```bash
kubectl create namespace keda
helm repo add kedacore https://kedacore.github.io/charts
helm repo update
helm install keda kedacore/keda --namespace keda
```

---

### 4. Verify Metric Export

Check that Prometheus is scraping the queue length metric `vllm:num_requests_waiting`.

```bash
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090
```

In a separate terminal:

```bash
curl -G 'http://localhost:9090/api/v1/query' --data-urlencode 'query=vllm:num_requests_waiting'
```

Example output:

```json
{
  "status": "success",
  "data": {
    "result": [
      {
        "metric": {
          "__name__": "vllm:num_requests_waiting",
          "pod": "vllm-llama3-deployment-vllm-xxxxx"
        },
        "value": [ 1749077215.034, "0" ]
      }
    ]
  }
}
```

This means that at the given timestamp, there were 0 pending requests in the queue.

---

### 5. Configure the ScaledObject

The following `ScaledObject` configuration is provided in `tutorials/assets/values-19-keda.yaml`. Review its contents:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: vllm-scaledobject
  namespace: default
spec:
  scaleTargetRef:
    name: vllm-llama3-deployment-vllm
  minReplicaCount: 1
  maxReplicaCount: 2
  pollingInterval: 15
  cooldownPeriod: 30
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus-operated.monitoring.svc:9090
        metricName: vllm:num_requests_waiting
        query: vllm:num_requests_waiting
        threshold: '5'
```

Apply the ScaledObject:

```bash
cd ../tutorials
kubectl apply -f assets/values-19-keda.yaml
```

This tells KEDA to:

* Monitor `vllm:num_requests_waiting`
* Scale between 1 and 2 replicas
* Scale up when the queue exceeds 5 requests

---

### 6. Test Autoscaling

Watch the deployment:

```bash
kubectl get hpa -n default -w
```

You should initially see:

```plaintext
NAME                         REFERENCE                                TARGETS     MINPODS   MAXPODS   REPLICAS
keda-hpa-vllm-scaledobject   Deployment/vllm-llama3-deployment-vllm   0/5 (avg)   1         2         1
```

`TARGETS` shows the current metric value vs. the target threshold.
`0/5 (avg)` means the current value of `vllm:num_requests_waiting` is 0, and the threshold is 5.

Generate load:

```bash
kubectl port-forward svc/vllm-router-service 30080:80
```

In a separate terminal:

```bash
python3 assets/example-10-load-generator.py --num-requests 100 --prompt-len 3000
```

Within a few minutes, the `REPLICAS` value should increase to 2.

---

### 7. Cleanup

To remove KEDA configuration and observability components:

```bash
kubectl delete -f assets/values-19-keda.yaml
helm uninstall keda -n keda
kubectl delete namespace keda

cd ../observability
bash uninstall.sh
```

---

## Additional Resources

* [KEDA Documentation](https://keda.sh/docs/)
