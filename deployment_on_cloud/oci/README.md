# Setting up OKE vLLM stack with one command

This script automatically configures an OKE (Oracle Kubernetes Engine) LLM inference cluster on Oracle Cloud Infrastructure.

## Installing Prerequisites

Before running this setup, ensure you have:

- [OCI CLI](https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/cliinstall.htm) installed and configured
- [jq](https://jqlang.github.io/jq/download/) for JSON parsing
- [Kubectl](https://kubernetes.io/docs/tasks/tools/#kubectl)
- [Helm](https://helm.sh/docs/intro/install/)
- GPU quota in your OCI tenancy (request via support ticket if needed)

## TL;DR

### Set up

> [!CAUTION]
> This script requires cloud resources and will incur costs. Please make sure all resources are shut down properly.

To run the service, go to the `deployment_on_cloud/oci/` folder and run the following command:

```bash
cd deployment_on_cloud/oci/
./entry_point.sh setup
```

Or with a custom Helm values file (run from the `deployment_on_cloud/oci/` directory):

```bash
./entry_point.sh setup ./production_stack_specification.yaml
```

### Clean up

To clean up the service, run the following command:

```bash
./entry_point.sh cleanup
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OCI_COMPARTMENT_ID` | Required | OCI compartment OCID for resources |
| `OCI_PROFILE` | `DEFAULT` | OCI CLI profile name |
| `OCI_REGION` | `us-ashburn-1` | OCI region |
| `CLUSTER_NAME` | `production-stack` | OKE cluster name |
| `PRIVATE_CLUSTER` | `true` | Use private endpoint with Bastion (no public IP) |
| `GPU_NODE_POOL_NAME` | `gpu-pool` | GPU node pool name |
| `GPU_NODE_COUNT` | `1` | Number of GPU nodes |
| `GPU_SHAPE` | `VM.GPU.A10.1` | GPU compute shape |

### GPU Shapes

| Shape | GPUs | GPU Type | Memory | Use Case |
|-------|------|----------|--------|----------|
| `VM.GPU.A10.1` | 1 | A10 | 24GB | 7B-13B models |
| `VM.GPU.A10.2` | 2 | A10 | 48GB | Tensor parallel small |
| `BM.GPU.A100-v2.8` | 8 | A100 80GB | 640GB | 70B models |
| `BM.GPU.H100.8` | 8 | H100 | 640GB | Large models, RDMA |
| `BM.GPU4.8` | 8 | A100 40GB | 320GB | Cost-effective large models |

### Storage Options

The default configuration uses OCI Block Volumes with encryption:

```yaml
storageClassName: oci-block-storage-enc
```

For multi-node deployments requiring shared storage, use OCI File Storage:

```yaml
storageClassName: oci-fss
pvcAccessMode:
  - ReadWriteMany
```

### Private Cluster Access

By default, the cluster uses a private endpoint (no public IP) with OCI Bastion for secure access. After setup, you'll need to create an SSH tunnel:

1. Create a bastion session:
```bash
oci bastion session create-port-forwarding \
  --bastion-id <BASTION_ID> \
  --target-private-ip <CLUSTER_PRIVATE_IP> \
  --target-port 6443 \
  --session-ttl 10800 \
  --ssh-public-key-file ~/.ssh/id_rsa.pub
```

2. Start SSH tunnel (using session ID from step 1):
```bash
ssh -i ~/.ssh/id_rsa -N -L 6443:<CLUSTER_PRIVATE_IP>:6443 \
  -o IdentitiesOnly=yes \
  <SESSION_ID>@host.bastion.<REGION>.oci.oraclecloud.com
```

3. Access kubectl:
```bash
kubectl get nodes
```

To use a public endpoint instead (not recommended for production):
```bash
export PRIVATE_CLUSTER=false
./entry_point.sh setup
```

## Advanced Usage

### Multi-GPU Tensor Parallelism

For bare metal GPU shapes (BM.GPU.*), configure tensor parallelism:

```bash
export GPU_SHAPE="BM.GPU.H100.8"
./entry_point.sh setup multi-gpu-values.yaml
```

See `production_stack_specification.yaml` for tensor parallelism configuration.

### RDMA Multi-Node

For multi-node pipeline parallelism with RDMA, see the `rdma/` directory.

### OCI Data Science

For managed model deployment using OCI Data Science, see the `data-science/` directory.
