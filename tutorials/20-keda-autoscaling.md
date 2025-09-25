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
  * [7. Scale down to zero](#7-scale-down-to-zero)
  * [8. Cleanup](#8-cleanup)
* [Additional Resources](#additional-resources)

---

> **Note**: This tutorial only supports non-disaggregated prefill request autoscaling.

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

The following `ScaledObject` configuration is provided in `tutorials/assets/values-20-keda.yaml`. Review its contents:

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
  cooldownPeriod: 360
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
kubectl apply -f assets/values-20-keda.yaml
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

### 7. Scale Down to Zero

Sometimes you want to scale down to zero replicas when there's no traffic. This is a unique capability of KEDA compared to Kubernetes' HPA, which always maintains at least one replica. Scale-to-zero is particularly useful for:

* **Cost optimization**: Eliminate resource usage during idle periods
* **Resource efficiency**: Free up GPU resources for other workloads
* **Cold start scenarios**: Scale up only when requests arrive

We provide this capability through a dual-trigger configuration. To configure it, modify the `tutorials/assets/values-20-keda.yaml`:

```yaml
# KEDA ScaledObject for vLLM deployment with scale-to-zero capability
# This configuration enables automatic scaling of vLLM pods based on queue length metrics
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: vllm-scaledobject
  namespace: default
spec:
  scaleTargetRef:
    name: vllm-llama3-deployment-vllm
  minReplicaCount: 0  # Allow scaling down to zero
  maxReplicaCount: 2
  # How often KEDA should check the metrics (in seconds)
  pollingInterval: 15
  # How long to wait before scaling down after scaling up (in seconds)
  cooldownPeriod: 360
  # Scaling triggers configuration
  triggers:
    # Trigger 1: Queue-based scaling
    - type: prometheus
      metadata:
        # Prometheus server address within the cluster
        serverAddress: http://prometheus-operated.monitoring.svc:9090
        # Name of the metric to monitor
        metricName: vllm:num_requests_waiting
        # Prometheus query to fetch the metric
        query: vllm:num_requests_waiting
        # Threshold value that triggers scaling
        # When queue length exceeds this value, KEDA will scale up
        threshold: '5'
    # Trigger 2: Traffic-based "keepalive" - prevents scale-to-zero when there's active traffic
    - type: prometheus
      metadata:
        serverAddress: http://prometheus-operated.monitoring.svc:9090
        metricName: vllm:incoming_keepalive
        # This query returns 1 if there's any incoming traffic in the last minute, 0 otherwise
        query: sum(rate(vllm:num_incoming_requests_total[1m]) > bool 0)
        threshold: "1"
```

**How the dual-trigger system works:**

1. **Queue trigger**: Scales up when `vllm:num_requests_waiting > 5`
2. **Traffic trigger**: Prevents scale-to-zero when there's active incoming traffic (rate > 0 in the last minute)
3. **Scale-to-zero**: Only occurs when both triggers are below their thresholds (no queue AND no traffic)

Apply the updated configuration:

```bash
kubectl apply -f assets/values-20-keda.yaml
```

**Test the scale-to-zero behavior:**

1. **Monitor the pods:**

   ```bash
   kubectl get pods -w
   ```

2. **Wait for scale-down:**
   Within a few minutes, you should see the backend pod get terminated, meaning KEDA decided to scale down to zero.

3. **Test scale-up from zero:**

   ```bash
   kubectl port-forward svc/vllm-router-service 30080:80
   ```

   In a separate terminal:

   ```bash
   curl -X POST http://localhost:30080/v1/completions \
     -H "Content-Type: application/json" \
     -d '{
       "model": "meta-llama/Llama-3.1-8B-Instruct",
       "prompt": "Once upon a time,",
       "max_tokens": 10
     }'
   ```

   You should initially get a HTTP 503 error saying the service is temporarily unavailable. However, within a few minutes, you should see a fresh pod being brought up and the same query should succeed.

**Expected behavior:**

* **Scale down**: Pods terminate when there's no traffic and no queued requests
* **Scale up**: New pods start when requests arrive, even from zero replicas
* **Cold start delay**: First request after scale-to-zero will experience a delay while the pod initializes

---

### 8. Cleanup

To remove KEDA configuration and observability components:

```bash
kubectl delete -f assets/values-20-keda.yaml
helm uninstall keda -n keda
kubectl delete namespace keda

cd ../observability
bash uninstall.sh
```

---

## Additional Resources

* [KEDA Documentation](https://keda.sh/docs/)
