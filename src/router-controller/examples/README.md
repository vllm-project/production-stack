# StaticRoute Controller Example

This example demonstrates how to deploy the StaticRoute controller, the vllm_router, and the StaticRoute CRD.

## Prerequisites

- Kubernetes cluster
- kubectl
- kustomize

## Deployment Steps

### Option 1: Using the Deployment Script

```bash
# Make the script executable
chmod +x deploy.sh

# Run the deployment script
./deploy.sh
```

### Option 2: Manual Deployment

### 1. Deploy the StaticRoute Controller

```bash
# Clone the repository
git clone https://github.com/vllm-project/production-stack.git
cd production-stack/router-controller

# Build and deploy the controller
make deploy
```

### 2. Deploy the vllm_router

```bash
# Apply the vllm_router deployment
kubectl apply -f config/samples/vllm_router_deployment.yaml
```

### 3. Create a StaticRoute Resource

```bash
# Apply the StaticRoute resource
kubectl apply -f config/samples/production-stack_v1alpha1_staticroute.yaml
```

### 4. Verify the Deployment

```bash
# Check the StaticRoute resource
kubectl get staticroutes

# Check the ConfigMap
kubectl get configmaps vllm-router-config

# Check the vllm_router deployment
kubectl get deployments vllm-router

# Check the vllm_router service
kubectl get services vllm-router

# Check the vllm_router pods
kubectl get pods -l app=vllm-router
```

### 5. Test the vllm_router

```bash
# Port-forward the vllm_router service
kubectl port-forward svc/vllm-router 8000:8000

# In another terminal, test the vllm_router
curl http://localhost:8000/health
```

## Cleanup

### Option 1: Using the Cleanup Script

```bash
# Make the script executable
chmod +x cleanup.sh

# Run the cleanup script
./cleanup.sh
```

### Option 2: Manual Cleanup

```bash
# Delete the StaticRoute resource
kubectl delete staticroutes staticroute-sample

# Delete the vllm_router deployment
kubectl delete -f config/samples/vllm_router_deployment.yaml

# Undeploy the controller
cd production-stack/router-controller
make undeploy
```

## How it Works

1. The StaticRoute controller watches for StaticRoute resources.
2. When a StaticRoute is created or updated, the controller creates or updates a ConfigMap with the dynamic configuration.
3. The vllm_router is configured to use the ConfigMap with the `--dynamic-config-json` option.
4. The controller checks the health endpoint of the vllm_router to verify that the configuration is valid.

## Troubleshooting

### Check the Controller Logs

```bash
# Get the controller pod name
kubectl get pods -n router-controller-system

# Check the controller logs
kubectl logs -n router-controller-system <controller-pod-name>
```

### Check the vllm_router Logs

```bash
# Get the vllm_router pod name
kubectl get pods -l app=vllm-router

# Check the vllm_router logs
kubectl logs <vllm-router-pod-name>
```

### Check the ConfigMap

```bash
# Get the ConfigMap
kubectl get configmaps vllm-router-config -o yaml
```

### Check the StaticRoute Status

```bash
# Get the StaticRoute status
kubectl get staticroutes staticroute-sample -o yaml
```
