# VLLM Inference Engine Controller Installation Guide

## Prerequisites

1. Kubernetes cluster (v1.19 or higher)
2. kubectl configured to communicate with your cluster
3. Go 1.24 (required, as specified in go.mod)
4. make
5. Docker (for building and pushing images)

## Step 1: Install Go 1.24

```bash
# Download and install Go 1.24
cd /tmp
wget https://go.dev/dl/go1.24.0.linux-amd64.tar.gz
sudo rm -rf /usr/local/go
sudo tar -C /usr/local -xzf go1.24.0.linux-amd64.tar.gz
export PATH=$PATH:/usr/local/go/bin

# Verify Go installation
go version  # Should show go1.24.0
```

## Step 2: Install the CRD

```bash
# Navigate to the controller directory
cd /mnt/data/prs/pdd/production-stack/vllm-pd-disagg-config/direct-controller

# Clean up any existing controller-gen installation
rm -f ~/go/bin/controller-gen

# Install the latest controller-gen
go install sigs.k8s.io/controller-tools/cmd/controller-gen@latest

# Install the CRD
make install
```

## Step 3: Build the Controller

```bash
# Build the controller binary
make
```

## Step 4: Build and Push the Container Image

Now build and push the image:

```bash
# Build the Docker image
make docker-build IMG=<your-registry>/inference-engine-controller:tag

# Push the image to your registry
make docker-push IMG=<your-registry>/inference-engine-controller:tag
```

## Step 5: Deploy the Controller

```bash
# Deploy the controller to your cluster
# kubectl set image deployment/controller-manager -n vllm-system manager=1nfinity/inference-engine-controller:latest
make deploy IMG=<your-registry>/inference-engine-controller:tag
```

## Step 6: Verify the Installation

```bash
# Check if the controller is running
kubectl get pods -n vllm-system

# Check if the CRD is installed
kubectl get crd | grep inferenceengines
```

## Step 7: Create an InferenceEngine Resource

Create a YAML file (e.g., `inference-engine.yaml`) with your desired configuration. Here's a basic example:

```yaml
apiVersion: production-stack.vllm.ai/v1alpha1
kind: InferenceEngine
metadata:
  name: sample-engine
spec:
  modelConfig:
    modelName: "meta-llama/Llama-2-7b-chat-hf"
    trustRemoteCode: false
    maxNumBatchedTokens: 2048
    enableChunkedPrefill: false
  deploymentMode: "basic"
  resources:
    default:
      limits:
        nvidia.com/gpu: "1"
        cpu: "8"
        memory: "32Gi"
      requests:
        nvidia.com/gpu: "1"
        cpu: "4"
        memory: "16Gi"
  replicas:
    default: 1
  storage:
    size: "100Gi"
    storageClass: "standard"
  serviceConfig:
    default:
      port: 8000
      type: ClusterIP
```

Apply the configuration:

```bash
kubectl apply -f inference-engine.yaml
```

## Troubleshooting

If you encounter any issues:

1. For Go version issues:
   - Make sure you're using Go 1.24 exactly
   - Verify with `go version`

2. For controller-gen issues:
   - Remove existing installation: `rm -f ~/go/bin/controller-gen`
   - Reinstall: `go install sigs.k8s.io/controller-tools/cmd/controller-gen@latest`

3. For Docker build issues:
   - Make sure all source files are included in the Dockerfile COPY commands
   - Verify that the pkg/ directory exists and contains the resources package
   - Check that the Dockerfile is using the correct Go version (1.24)

4. For deployment issues:
   - Check logs: `kubectl logs -n vllm-system -l control-plane=controller-manager`
   - Verify CRD installation: `kubectl get crd inferenceengines.production-stack.vllm.ai`

## Cleanup

To remove the controller and CRD:

```bash
# Delete all InferenceEngine resources
kubectl delete inferenceengines --all

# Uninstall the CRD
make uninstall

# Undeploy the controller
make undeploy
```

## Notes

- Replace `<your-registry>` with your actual container registry when building and pushing the image
- The controller requires Go 1.24 specifically, as specified in the go.mod file
- Make sure your Kubernetes cluster has sufficient resources for the inference engine deployment
- The example configuration uses a basic deployment mode, but you can also use the disaggregated mode for more complex setups
- If you encounter the "no required module provides package" error, make sure the pkg/ directory is properly included in the Docker build context
