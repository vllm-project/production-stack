# OCI Integration for vLLM Production Stack

## Table of Contents

- [Summary](#summary)
- [Motivation](#motivation)
- [Proposal](#proposal)

## Summary

This proposal adds Oracle Cloud Infrastructure (OCI) as a first-class cloud provider for the vLLM production stack, alongside AWS, Azure, and GCP. The integration includes automated OKE (Oracle Kubernetes Engine) deployment scripts, storage configuration for OCI Block Volumes and File Storage, GPU node pool management, and documentation. Advanced features include RDMA cluster networking for multi-node deployments and OCI Data Science integration for managed model deployment.

## Motivation

Oracle Cloud Infrastructure offers competitive GPU capabilities including A10, A100 80GB, H100, and H200 GPUs with RDMA networking support. Despite these capabilities, there is no official vLLM production stack deployment guide for OCI, creating a gap in cloud provider coverage.

- **Why is this feature needed?** AWS, Azure, and GCP have official Terraform + deployment scripts in the vLLM production stack, but OCI does not. This limits adoption by enterprises using OCI for AI/ML workloads.
- **What use cases does it address?** Organizations running GPU workloads on OCI need a streamlined path to deploy vLLM at scale with proper storage, networking, and GPU configuration.
- **What current limitations does it alleviate?** Users must manually configure OKE clusters, storage classes, and GPU tolerations. This proposal provides automation and best practices.

### Goals

- Provide one-click OKE cluster creation with GPU node pools
- Configure OCI Block Volume storage for model weights persistence
- Support OCIR (Oracle Container Registry) image pull secrets
- Document GPU shape options (A10, A100, H100, H200)
- Enable RDMA cluster networking for multi-node tensor/pipeline parallelism
- Provide OCI Data Science integration as an alternative managed deployment path

### Non-Goals

- Terraform modules (may be added in future PR)
- Integration with OCI Resource Manager stacks
- Cost optimization automation
- OCI Identity federation setup

## Proposal

### Proposed Changes

#### Phase 1: Basic OKE Deployment

Add `deployment_on_cloud/oci/` directory with:

```text
deployment_on_cloud/oci/
  README.md                            # Main documentation
  entry_point.sh                       # One-click deploy/cleanup
  clean_up.sh                          # Resource cleanup
  production_stack_specification.yaml  # OCI-specific Helm values
  oci-block-storage-sc.yaml           # StorageClass for Block Volumes
```

**entry_point.sh** provides:

- OKE cluster creation with configurable GPU node pools
- Block Volume CSI StorageClass configuration
- NVIDIA device plugin deployment
- vLLM Helm chart installation
- Service exposure via OCI Load Balancer

**StorageClass** uses OCI Block Volume CSI driver:

```yaml
storageClassName: oci-block-storage-enc
provisioner: blockvolume.csi.oraclecloud.com
```

**Helm Values** include OCI-specific configuration:

```yaml
nodeSelector:
  app: gpu
tolerations:
  - key: "nvidia.com/gpu"
    operator: "Exists"
    effect: "NoSchedule"
imagePullSecrets:
  - name: iad.ocir.io
```

#### Phase 2: Tutorial Documentation

Add `tutorials/cloud_deployments/05-OCI-OKE-deployment.md` covering:

1. Prerequisites (OCI CLI, kubectl, GPU quota)
2. OKE cluster creation with GPU nodes
3. Storage configuration
4. vLLM deployment via Helm
5. Testing inference endpoint
6. GPU shape reference table

#### Phase 3: Multi-GPU Support

Add tensor parallelism configuration for bare metal GPU shapes:

```yaml
tensorParallelSize: 8
extraArgs:
  - "--max-model-len=8192"
  - "--gpu-memory-utilization=0.95"
nodeSelector:
  node.kubernetes.io/instance-type: "BM.GPU.H100.8"
```

#### Phase 4: RDMA Multi-Node

Add `deployment_on_cloud/oci/rdma/` with:

- Cluster Network configuration for RoCEv2
- NCCL environment variables for RDMA
- Multi-node pipeline parallelism example

OCI RDMA provides 2-6.5 microsecond latency, enabling efficient multi-node inference.

#### Phase 5: OCI Data Science Integration

Add `deployment_on_cloud/oci/data-science/` with:

- Model deployment using OCI Data Science Model Deployment
- ADS SDK integration example
- Managed endpoint configuration

### Implementation Details/Notes/Constraints

- **Architecture / Components:** Adds new cloud provider directory under `deployment_on_cloud/`, tutorial under `tutorials/cloud_deployments/`, no changes to existing code
- **Interface Changes:** None - follows existing patterns from AWS/Azure/GCP deployments
- **Performance Considerations:** RDMA networking provides significant latency improvements for multi-node deployments
- **Resource Constraints:** GPU quota must be available in user's OCI tenancy

### Test plans

- **Unit Tests:** Shell script linting with shellcheck
- **Integration/E2E Tests:** Manual testing on OCI with:
  - VM.GPU.A10.1 for single GPU deployment
  - BM.GPU.A100-v2.8 for multi-GPU tensor parallelism
  - BM.GPU.H100.8 for RDMA multi-node
- **Negative Tests:** Verify graceful handling of missing OCI CLI, insufficient quota, invalid compartment OCID

## Drawbacks

- Adds maintenance burden for OCI-specific scripts
- OCI CLI required (not as widely installed as AWS CLI)
- RDMA configuration requires specific bare metal GPU shapes

## Alternatives

- **Terraform modules:** More declarative but higher complexity; can be added later
- **OCI Resource Manager:** OCI-native but less portable
- **Do nothing:** Users continue manual configuration, limiting OCI adoption

## Implementation Timeline / Phases

1. **PR 1:** Basic OKE deployment (`deployment_on_cloud/oci/` + tutorial)
2. **PR 2:** Multi-GPU tensor parallelism support
3. **PR 3:** RDMA cluster networking for multi-node
4. **PR 4:** OCI Data Science integration

## References

- [OCI Container Engine for Kubernetes (OKE)](https://docs.oracle.com/en-us/iaas/Content/ContEng/home.htm)
- [OCI GPU Shapes](https://docs.oracle.com/en-us/iaas/Content/Compute/References/computeshapes.htm#gpu-shapes)
- [OCI RDMA Cluster Networking](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/managingclusternetworks.htm)
- [OCI Block Volume CSI Driver](https://github.com/oracle/oci-cloud-controller-manager/blob/master/docs/block-volume-csi.md)
- [OCI Data Science Model Deployment](https://docs.oracle.com/en-us/iaas/data-science/using/model-dep-about.htm)
