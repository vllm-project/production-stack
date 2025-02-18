# Tutorial: Create Router Ingress with NGINX Ingress Controller

## Introduction

This tutorial demonstrates how to use the [NGINX Ingress Controller](https://github.com/kubernetes/ingress-nginx) to allow your vLLM-hosted models to be reachable from outside the Kubernetes cluster. While this example uses NGINX, a similar approach is possible with any other ingress controller.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Step 1: Deploying NGINX Ingress Controller](#step-1-deploying-nginx-ingress-controller)
3. [Step 2: Deploying the Helm Chart](#step-2-deploying-the-helm-chart)
4. [Step 3: Testing the External Connection](#step-3-testing-the-external-connection)

## Prerequisites

- Completion of the following tutorials:
  - [00-install-kubernetes-env.md](00-install-kubernetes-env.md)
  - [01-minimal-helm-installation.md](01-minimal-helm-installation.md)
  - [02-basic-vllm-config.md](02-basic-vllm-config.md)
- A Kubernetes environment with GPU support.

## Step 1: Deploying NGINX Ingress Controller

When using MiniKube, you can easily enable the ingress controller using the command below:
`minikube addons enable ingress`

When you are deploying on a production cluster, you will likely want to use the [Helm chart approach](https://kubernetes.github.io/ingress-nginx/deploy/#bare-metal-clusters) instead.

## Step 2: Deploying the Helm Chart

Deploy the Helm chart using the predefined configuration file:

```bash
helm repo add vllm https://vllm-project.github.io/production-stack
helm install vllm vllm/vllm-stack -f tutorials/assets/values-06-ingress-controller.md
```

Looking at the example values file, you will notice that the `routerSpec` section contains the configuration for the ingress. The default values in this example are below:

```yaml
routerSpec:
  enableRouter: true
  ingress:
    # Builds the ingress resource on the router service
    enabled: true
    className: "nginx"

    # Example annotations
    annotations:
      nginx.ingress.kubernetes.io/enable-access-log: "true"
      nginx.ingress.kubernetes.io/enable-opentelemetry: "true"

    hosts:
      - host: router.example.com
        paths:
          - path: /
            pathType: Prefix
```

For an ingress to be enabled, both the `routerSpec.enableRouter` and `routerSpec.ingress.enabled` values need to be set to `true`.

The `className` value is used to specify the type of ingress that should be used. `nginx` is the standard for NGINX ingresses, but you may see other examples, such as `alb` if you're using the AWS ALB Ingress Controller instead of NGINX.

The `annotations` section allows you to add any other annotations to the ingress, which change its configuration. These annotations can be used to change the traffic forwarding behavior, enable authentication, enable logging, and many other options. The full list of annotations can be found on the [NGINX Ingress Controller Annotations](https://kubernetes.github.io/ingress-nginx/user-guide/nginx-configuration/annotations) page.

The `hosts` block is used to configure the DNS name (or `host`) of the ingress where the router can be reached, and the paths that the ingress will forward traffic to.

## Step 3: Testing the External Connection

If you deployed on MiniKube, test the stack's OpenAI-compatible API by querying the available models:

```bash
INGRESS_IP=$(kubectl get ing -o json | jq -r .items[0].status.loadBalancer.ingress[0].ip)
curl -o- http://$INGRESS_IP/models
```

Note that if you're using zsh, you'll need to use these commands instead:

```zsh
INGRESS_IP=$(kubectl get ing -o json | jq -r .items\[0\].status.loadBalancer.ingress\[0\].ip)
curl -o- http://$INGRESS_IP/models
```

If you deployed onto a cluster using the NGINX Ingress Controller Helm chart, and have a service configured to deploy the DNS records, you can instead try:

```bash
INGRESS_DNS=$(kubectl get ing -o json | jq -r .items[0].spec.rules[0].host)
curl -o- https://$INGRESS_DNS/models
```
