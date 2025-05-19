kubectl delete -f configs/vllm/gpu-deployment.yaml
VERSION=v0.3.0
kubectl delete -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/$VERSION/manifests.yaml
kubectl delete -f configs/inferencemodel.yaml

kubectl delete -f configs/inferencepool-resources.yaml

KGTW_VERSION=v2.0.2
kubectl delete -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/raw/main/config/manifests/gateway/kgateway/gateway.yaml --ignore-not-found
kubectl delete -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/raw/main/config/manifests/gateway/kgateway/httproute.yaml --ignore-not-found
