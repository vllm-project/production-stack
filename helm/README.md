# vLLM Production Stack helm chart

This helm chart lets users deploy multiple serving engines and a router into the Kubernetes cluster.

## Key features

- Support running multiple serving engines with multiple different models
- Load the model weights directly from the existing PersistentVolumes

## Prerequisites

1. A running Kubernetes cluster with GPU. (You can set it up through `minikube`: <https://minikube.sigs.k8s.io/docs/tutorials/nvidia/>)
2. [Helm](https://helm.sh/docs/intro/install/)

## Install the helm chart

```bash
helm install llmstack . -f values-example.yaml
```

## Uninstall the deployment

run `helm uninstall llmstack`

## Configure the deployments

See `helm/values.yaml` for mode details.
