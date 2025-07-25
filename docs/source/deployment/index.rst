Deployment Overview
===================

The vLLM Production Stack provides three primary deployment options to suit different use cases and infrastructure requirements. Each option offers unique capabilities and advantages:

Deployment Options
------------------

.. toctree::
   :maxdepth: 1

   helm
   crd
   gateway-inference-extension

**Helm Chart Deployment**
   The standard deployment method using Helm charts for Kubernetes. This provides a streamlined way to deploy vLLM with configurable parameters for models, resources, and routing logic.

**Custom Resource Definitions (CRD)**
   Deploy using Kubernetes CRDs for more advanced configurations and operator-based management. This option provides greater flexibility and integration with Kubernetes-native workflows.

**Gateway Inference Extension**
   Advanced deployment option that enables inference capabilities through gateway infrastructure, supporting both individual inference models and inference pools with sophisticated routing capabilities.

Choose the deployment option that best fits your infrastructure requirements and use case complexity.
