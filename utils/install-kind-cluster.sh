# Note that this makes heavy use of Sam Stoelinga's guide https://www.substratus.ai/blog/kind-with-gpus

echo "Setting NVIDIA container toolkit (nvidia-ctk) to be docker's default runtime..." 
# This allows Docker containers to access GPU hardware
sudo nvidia-ctk runtime configure --runtime=docker --set-as-default
echo "Restarting docker..."
sudo systemctl restart docker

echo "Allowing volume mounts..."
# This is necessary for GPU passthrough in containerized environments
sudo sed -i '/accept-nvidia-visible-devices-as-volume-mounts/c\accept-nvidia-visible-devices-as-volume-mounts = true' /etc/nvidia-container-runtime/config.toml

kind create cluster --name single-node-cluster --config - <<EOF
apiVersion: kind.x-k8s.io/v1alpha4
kind: Cluster
nodes:
- role: control-plane
  image: kindest/node:v1.27.3@sha256:3966ac761ae0136263ffdb6cfd4db23ef8a83cba8a463690e98317add2c9ba72
  # required for GPU workaround
  extraMounts:
    - hostPath: /dev/null
      containerPath: /var/run/nvidia-container-devices/all
EOF

echo "Adding nvidia helm repo and installing its gpu-operator helm chart..."
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia || true
helm repo update
helm install --wait --generate-name \
     -n gpu-operator --create-namespace \
     nvidia/gpu-operator --set driver.enabled=false

# echo "Creating test pod..."
# kubectl apply -f - << EOF
# apiVersion: v1
# kind: Pod
# metadata:
#   name: cuda-vector-add-test
# spec:
#   restartPolicy: OnFailure
#   containers:
#   - name: cuda-vector-add-test
#     image: "nvcr.io/nvidia/k8s/cuda-sample:vectoradd-cuda11.7.1-ubuntu20.04"
#     resources:
#       limits:
#         nvidia.com/gpu: 1
# EOF