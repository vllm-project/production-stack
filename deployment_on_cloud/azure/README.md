# Setting up AKS vLLM stack with one command

This script automatically configures an AKS LLM inference cluster.

## Installing Prerequisites

Before running this setup, ensure you have:

- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli)
- [Kubectl](https://kubernetes.io/docs/tasks/tools/#kubectl)
- [Helm](https://helm.sh/docs/intro/install/)

## TL;DR

### Set up

> [!CAUTION]
> This script requires cloud resources and will incur costs. Please make sure all resources are shut down properly.

To run the service, go to the [deployment_on_cloud/azure/](deployment_on_cloud/azure/) folder and run the following command:

```bash
cd deployment_on_cloud/azure/
./entry_point.sh setup
```

### Clean up

To clean up the service, run the following command:

```bash
cd deployment_on_cloud/azure/
./entry_point.sh cleanup
```
