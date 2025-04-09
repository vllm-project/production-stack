# Tutorial: Basic tracing/metrics/logs Collection using OpenTelemetry

## Introduction

This tutorial guides you through the basic configurations required to collect
traces, metrics, and logs from a vLLM serving engine in a Kubernetes environment
with GPU support. You will learn how to use OpenTelemetry tooling along with
the Jaeger distributed tracing observability platform to monitor running vLLM
instances. You will learn how to specify the tracing configuration with
necessary environment variables (like `OTEL_SERVICE_NAME`,
`OTEL_EXPORTER_OTLP_ENDPOINT`, and `OTEL_RESOURCE_ATTRIBUTES`).

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Step 1: Preparing the Jaeger Configuration File](#step-1-preparing-the-jaeger-configuration-file)
3. [Step 2: Preparing the OpenTelemetry Collector File](#step-2-preparing-the-opentelemetry-collector-file)
4. [Step 3: Configuring Model and Monitoring](#step-3-configuring-model-and-monitoring)

## Prerequisites

- A Kubernetes environment with GPU support, as set up in the
  [00-install-kubernetes-env tutorial](00-install-kubernetes-env.md).
- Helm installed on your system.
- Access to a HuggingFace token (`HF_TOKEN`).
- A self-defined api key or an existing secret (`VLLM_API_KEY`).

## Step 1: Preparing the Jaeger Configuration File

1. Locate the example configuration files
   [`tutorials/assets/otel-example/{jaeger, jaeger-query, jaeger-collector}.yaml`](assets/otel-example/).
2. Open the files and examine the following fields:
   - Specify your desired ports for `jaeger-collector` and `jaeger-query`
   services for trace storage and retrieval, respectively.
   - Verify that `COLLECTOR_OTLP_ENABLED` is set to `true`; this enables
   Jaeger's native support for OpenTelemetry

### Explanation of Key Items in Jaeger Files

- **`ports`**: The ports through which Jaeger performs its operations
(collection and querying in this case).
- **`name`**: The unique identifier for your Jaeger deployment.
- **`image`**: The single Docker image that runs all Jaeger's backend parts as
well as its UI in a container.
- **`type`**: The ClusterIP type ensures the query service is only reachable
from within the cluster.

## Step 2: Preparing the OpenTelemetry Collector File

1. Locate the example collector files
   [`tutorials/assets/otel-example/{otel-collector, otel-collector-config}.yaml`](assets/otel-example/).
2. Open the file and examine the following fields:
   - Specify the `receivers`, `processors`, and `exporters` of the collector
   - The OpenTelemetry collection is an intermediary step of collecting traces
   from the vLLM service and then providing these to Jaeger for its UI.
   - The `resources` specify the compute resources available to the container
   running the OpenTelemetry collector.

## Step 3: Configuring Model and Monitoring

1. Feel free to inspect the `values-12-otel-vllm.yaml` file. Note that the
   `OTEL_EXPORTER_OTLP_ENDPOINT` specification enables metrics, traces, and
   logs to be collected. Further configurations can be explored
   [here](https://opentelemetry.io/docs/languages/sdk-configuration/otlp-exporter/).

   Run the following from the `tutorials/assets` directory:

   ```bash
   sudo kubectl apply -f otel-example/jaeger.yaml
   sudo kubectl apply -f otel-example/jaeger-collector.yaml
   sudo kubectl apply -f otel-example/jaeger-query.yaml
   sudo kubectl apply -f otel-example/otel-collector-config.yaml
   sudo kubectl apply -f otel-example/otel-collector.yaml
   sudo helm install vllm ../../helm/ -f values-12-otel-vllm.yaml
   ```

   ```bash
   sudo kubectl get pods
   ```

   Expected output:

   You should see pods such as the following:

   ```plaintext
    NAME                                               READY   STATUS    RESTARTS   AGE
    jaeger-744484b5bc-rdrgn                            1/1     Running   0          13m
    otel-collector-859db69dd4-kj8x6                    1/1     Running   0          12m
    vllm-deployment-router-6888598c6-m6gl9             1/1     Running   0          12m
    vllm-opt125m-deployment-vllm-b489dfd8b-95gb5       1/1     Running   0          12m
   ```

   - The `vllm-deployment-router` pod acts as the router, managing requests and
    routing them to the appropriate model-serving pod.
   - The `vllm-opt125m-deployment-vllm` pod serves the actual model for
    inference.

2. Check service usage:

   ```bash
   sudo kubectl get services
   ```

   Expected output:

   Ensure there are services for the serving engine, router, jaeger-collector,
   and jaeger-query. Note that the OpenTelemetry deployment does not require
   its own service:

   ```plaintext
   NAME                      TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)        AGE
    jaeger-collector          ClusterIP   10.99.125.245   <none>        4317/TCP,4318/TCP   86m
    jaeger-query              ClusterIP   10.97.59.30     <none>        16686/TCP           86m
    vllm-engine-service   ClusterIP   10.102.6.58     <none>        80/TCP              86m
    vllm-router-service   ClusterIP   10.103.127.48   <none>        80/TCP              86m
   ```

   - The `vllm-engine-service` exposes the serving engine.
   - The `vllm-router-service` handles routing and load balancing across
     model-serving pods.
   - The `jaeger-collector` service handles collection of trace data from
   OpenTelemetry.
   - The `jaeger-query` service pulls data from the jaeger collector to use in
   the UI.

3. Expose the model and the Jaeger UI:

   ```bash
   sudo kubectl port-forward svc/vllm-router-service 30080:80
   sudo kubectl port-forward svc/jaeger-query 16686:16686
   ```

   Note that 30080:80 can be replaced with any TCP/UDP port and that port
   16686 is not used if a different `jaeger-query` port is chosen instead.

Please refer to Step 3 in the
[01-minimal-helm-installation](01-minimal-helm-installation.md) tutorial for
querying the deployed vLLM service. You can monitor all queries by navigating
to localhost:16686 or wherever your jaeger-query port is specified, select
`jaeger-all-in-one` from the Service dropdown menu on the Jaeger UI and click
"Find Traces" to yield the traces.

## Conclusion

In this tutorial, you configured and deployed a vLLM serving engine in a
Kubernetes environment, processed and exported resulting traces to Jaeger
using an OpenTelemetry collector, and viewed the traces in the Jaeger UI. For
further customization, please look at the various data sources available for
monitoring [here](https://opentelemetry.io/docs/collector/configuration/).
