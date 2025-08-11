# Using Gateway API for Ingress

This tutorial will guide you through configuring a HTTPS route with HTTP Redirect for the production stack router, using the [Kubernetes Gateway API](https://gateway-api.sigs.k8s.io/) and the helm chart.

## Table of Contents

* [Prerequisites](#prerequisites)
* [Overview](#overview)
* [Step 1: Configure the Gateway API](#step-1-configure-the-gateway-api)
  * [1.1 Install Gateway API CRDs](#11-install-gateway-api-crds)
  * [1.2 Install a Gateway controller](#12-install-a-gateway-controller)
* [Step 2: Deploy a Gateway](#step-2-deploy-a-gateway)
  * [2.1 Environment setup](#21-environment-setup)
  * [2.2 Set up a Gateway](#22-set-up-a-gateway)
* [Step 3: Deploy vLLM Production Stack](#step-3-deploy-vllm-production-stack)
  * [3.1 Deploy using Helm](#31-deploy-using-helm)
* [Step 4: Test deployment](#step-4-test-deployment)
* [Step 5: Uninstall](#step-5-uninstall)

## Prerequisites

Before starting this tutorial, ensure you have:

* A Kubernetes cluster with GPU nodes available
* `kubectl` configured to access your cluster
* `helm` installed
* Basic understanding of Kubernetes concepts

## Overview

The Gateway API is an official Kubernetes project focusing on building the next generation of Kubernetes Ingress, Load Balancing and Service Mesh APIs. Instead of creating Ingress objects, you instead create Route objects of different kinds and assign them to a Gateway.

## Step 1: Configure the Gateway API

### 1.1 Install Gateway API CRDs

Install the required Custom Resource Definitions (CRDs):

```bash
# Install Gateway API CRDs, https://gateway-api.sigs.k8s.io/guides/#installing-gateway-api
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.3.0/standard-install.yaml
```

### 1.2 Install a Gateway controller

To configure a gateway you will need a Gateway controller. There are several projects which implement a Gateway controller, see [](https://gateway-api.sigs.k8s.io/implementations/#gateway-controller-implementation-status) for a full list. For this tutorial, we will be using KGateway. Refer to the vendors documentation for configuring other controllers.

```bash
KGTW_VERSION=v2.0.3

# Install KGateway CRDs
helm upgrade -i --create-namespace --namespace kgateway-system --version $KGTW_VERSION kgateway-crds oci://cr.kgateway.dev/kgateway-dev/charts/kgateway-crds

# Install KGateway with inference extension enabled
helm upgrade -i --namespace kgateway-system --version $KGTW_VERSION kgateway oci://cr.kgateway.dev/kgateway-dev/charts/kgateway
```

## Step 2: Deploy a Gateway

### 2.1 Environment setup

Let's start by configuring a namespace for our gateway, and for the production stack later.

```bash
kubectl create namespace vllm-stack
```

Next, let's create a self signed certificate for the HTTPS route. For a production setup, this should be handled by something like cert-manager, or your internal CA.

```bash
mkdir example_certs
# root cert
openssl req -x509 -sha256 -nodes -days 365 -newkey rsa:2048 -subj '/CN=tutorial-ca' -keyout example_certs/root.key -out example_certs/root.crt

# create and issue certificate
openssl req -out example_certs/gateway.csr -newkey rsa:2048 -nodes -keyout example_certs/gateway.key -subj "/CN=llm-api/O=example.com"
openssl x509 -req -sha256 -days 365 -CA example_certs/root.crt -CAkey example_certs/root.key -set_serial 0 -in example_certs/gateway.csr -out example_certs/gateway.crt

# Create kubernetes TLS secret
kubectl create secret tls -n vllm-stack https \
  --key example_certs/gateway.key \
  --cert example_certs/gateway.crt
kubectl label secret https gateway=https --namespace vllm-stack
```

### 2.2 Set up a Gateway

The gateway acts as the entry point ingress traffic from outside the cluster. Each Gateway will use a LoadBalancer type service to bind an external IP address.

We will be using a self signed certificate for this tutorial.

```bash
# Create gateway with HTTP and HTTPS listener
kubectl apply -f- <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: llm-api-gateway
  namespace: vllm-stack
spec:
  gatewayClassName: kgateway
  listeners:
  - name: http
    port: 80
    protocol: HTTP
    hostname: llm-api.example.com
  - name: https
    port: 443
    protocol: HTTPS
    hostname: llm-api.example.com
    tls:
      mode: Terminate
      certificateRefs:
        - name: https
          kind: Secret
EOF
```

This gateway creates two listeners, one on port 443 for HTTPS, and one on port 80 for HTTP traffic. Notice how the https listener refers to the TLS secret created earlier for the certificate.

Check the IP address of the created load balancer service, and configure DNS as required.

## Step 3: Deploy vLLM Production Stack

### 3.1 Deploy using Helm

Let's install vLLM Production Stack using the helm chart, and the demo values in [values-22-gateway-api](assets/values-22-gateway-api.yaml)

```bash
helm repo add vllm https://vllm-project.github.io/production-stack
helm install -n vllm-stack vllm vllm/vllm-stack -f tutorials/assets/values-22-gateway-api.yaml
```

The values will deploy a single instance of the `facebook/opt-125m` model, enables the vllm router, and configure two HTTP routes.

## Step 4: Test deployment

You should now be able to test the deployment!

Go to `https://llm-api.example.com/v1/models`, or whatever you configured the domain as, and if everything is correct the `facebook/opt-125m` model should be listed.

Try going to `http://llm-api.example.com/v1/models` as well, and you should see that you automatically get redirected to the HTTPS site.

If we take a closer look at the values in the routerSpec, we see this configuration:

```yaml
routerSpec:
  enableRouter: true
  route:
    main:
      enabled: true
      hostnames:
        - llm-api.example.com
      parentRefs:
        - name: llm-api-gateway
          namespace: vllm-stack
          sectionName: https
      matches:
        - path:
            type: PathPrefix
            value: /
    http:
      enabled: true
      hostnames:
        - llm-api.example.com
      parentRefs:
        - name: llm-api-gateway
          namespace: vllm-stack
          sectionName: http
      httpsRedirect: true
```

The `main` route is created to match the hostname we defined earlier, and we also see that the `parentRefs` section matches the gateway name, namespace and section for the Gateway we created earlier.

The `http` route notably points to the `http` section, instead of the `https` section that `main` refers to. By also setting `httpsRedirect: true`, the helm chart will template out the required http redirect rules.

## Step 5: Uninstall

To uninstall all the resources installed on the cluster, run the following:

```bash
# Delete helm releases
helm uninstall vllm -n vllm-stack
helm uninstall kgateway -n kgateway-system
helm uninstall kgateway-crds -n kgateway-system
# Delete the namespaces last to ensure all resources are removed
kubectl delete ns kgateway-system --ignore-not-found=true
kubectl delete ns vllm-stack --ignore-not-found=true
# Delete Gateway extension CRDs
kubectl delete -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.3.0/standard-install.yaml --ignore-not-found=true
# Delete example certs
rm -r example_certs/
```
