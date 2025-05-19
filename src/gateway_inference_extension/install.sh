# Install KGateway CRDs first
KGTW_VERSION=v2.0.2
helm upgrade -i --create-namespace --namespace kgateway-system --version $KGTW_VERSION kgateway-crds oci://cr.kgateway.dev/kgateway-dev/charts/kgateway-crds
# Install gateway API CRDs
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.3.0/standard-install.yaml

# Install Gateway API inference extension CRDs
VERSION=v0.3.0
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/$VERSION/manifests.yaml

# Install KGateway with inference extension enabled
helm upgrade -i --namespace kgateway-system --version $KGTW_VERSION kgateway oci://cr.kgateway.dev/kgateway-dev/charts/kgateway --set inferenceExtension.enabled=true

# Apply VLLM deployment
kubectl apply -f configs/vllm/gpu-deployment.yaml

# Apply inference model and pool resources
kubectl apply -f configs/inferencemodel.yaml
kubectl apply -f configs/inferencepool-resources.yaml

# Apply Gateway and HTTPRoute resources
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/raw/main/config/manifests/gateway/kgateway/gateway.yaml
kubectl apply -f configs/httproute.yaml
