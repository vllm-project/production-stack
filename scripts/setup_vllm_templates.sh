#!/bin/bash

# Exit on error
set -e

# Configuration
PV_NAME="vllm-templates-pv"  # Fixed name for template storage
PVC_NAME="vllm-templates-pvc"  # Fixed name for template storage
STORAGE_SIZE="1Gi"
STORAGE_CLASS="standard"
HOST_TEMPLATES_DIR="/mnt/templates"  # This is where the PV will be mounted on the host
TEMP_POD_NAME="vllm-templates-setup"

echo "Setting up vLLM templates..."
echo "Using PV: $PV_NAME"
echo "Using PVC: $PVC_NAME"

# Check if host directory exists and create if needed
echo "Checking host directory at $HOST_TEMPLATES_DIR..."
if [ ! -d "$HOST_TEMPLATES_DIR" ]; then
    echo "Creating host directory at $HOST_TEMPLATES_DIR..."
    sudo mkdir -p "$HOST_TEMPLATES_DIR"
    sudo chmod 777 "$HOST_TEMPLATES_DIR"  # Allow read/write access
fi

# Verify directory permissions
if [ ! -w "$HOST_TEMPLATES_DIR" ]; then
    echo "Error: No write permission to $HOST_TEMPLATES_DIR"
    echo "Please ensure you have sudo access or the directory has proper permissions"
    exit 1
fi

# Create PersistentVolume with ReadWriteMany
echo "Creating PersistentVolume..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: $PV_NAME
spec:
  capacity:
    storage: $STORAGE_SIZE
  accessModes:
    - ReadWriteMany
  hostPath:
    path: /templates
    type: DirectoryOrCreate
  storageClassName: $STORAGE_CLASS
EOF

# Create PersistentVolumeClaim with ReadWriteMany
echo "Creating PersistentVolumeClaim..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: $PVC_NAME
spec:
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: $STORAGE_SIZE
  storageClassName: $STORAGE_CLASS
EOF

# Create temporary pod to clone and extract templates
echo "Creating temporary pod to download templates..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: $TEMP_POD_NAME
spec:
  containers:
  - name: template-setup
    image: ubuntu:latest
    command: ["/bin/bash", "-c"]
    args:
    - |
      apt-get update && apt-get install -y git
      git clone https://github.com/vllm-project/vllm.git /tmp/vllm
      cp /tmp/vllm/examples/*.jinja /templates/
      rm -rf /tmp/vllm
    volumeMounts:
    - name: templates-volume
      mountPath: /templates
  volumes:
  - name: templates-volume
    persistentVolumeClaim:
      claimName: $PVC_NAME
  restartPolicy: Never
EOF

# Wait for pod to complete
echo "Waiting for template download to complete..."
kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/vllm-templates-setup  --timeout=300s
# Delete the temporary pod
echo "Cleaning up temporary pod..."
kubectl delete pod $TEMP_POD_NAME

# Verify the setup
echo "Verifying setup..."
kubectl get pv $PV_NAME
kubectl get pvc $PVC_NAME

# List downloaded templates
echo "Downloaded templates:"
ls -l "$HOST_TEMPLATES_DIR"

echo "Setup complete! The templates are now available in the PersistentVolume."
echo "Host path: $HOST_TEMPLATES_DIR"
echo "You can now deploy the vLLM stack with tool calling support."
