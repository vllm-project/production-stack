#!/bin/bash
CLUSTER_NAME="production-stack"
ZONE="us-central1-a"
# Get the current GCP project ID
GCP_PROJECT=$(gcloud config get-value project)

# Ensure the project ID is retrieved correctly
if [ -z "$GCP_PROJECT" ]; then
  echo "Error: No GCP project ID found. Please set your project with 'gcloud config set project <PROJECT_ID>'."
  exit 1
fi

# Ensure a parameter is provided
if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <SETUP_YAML>"
  exit 1
fi

SETUP_YAML=$1


# Create the GKE cluster
gcloud beta container --project "$GCP_PROJECT" clusters create "$CLUSTER_NAME" \
  --zone "$ZONE" \
  --tier "standard" \
  --no-enable-basic-auth \
  --cluster-version "1.31.5-gke.1023000" \
  --release-channel "regular" \
  --machine-type "n2d-standard-8" \
  --image-type "COS_CONTAINERD" \
  --disk-type "pd-balanced" \
  --disk-size "100" \
  --metadata disable-legacy-endpoints=true \
  --scopes "https://www.googleapis.com/auth/devstorage.read_only",\
    "https://www.googleapis.com/auth/logging.write",\
    "https://www.googleapis.com/auth/monitoring",\
    "https://www.googleapis.com/auth/servicecontrol",\
    "https://www.googleapis.com/auth/service.management.readonly",\
    "https://www.googleapis.com/auth/trace.append" \
  --max-pods-per-node "110" \
  --num-nodes "1" \
  --logging=SYSTEM,WORKLOAD \
  --monitoring=SYSTEM,STORAGE,POD,DEPLOYMENT,STATEFULSET,DAEMONSET,HPA,CADVISOR,KUBELET \
  --enable-ip-alias \
  --network "projects/$GCP_PROJECT/global/networks/default" \
  --subnetwork "projects/$GCP_PROJECT/regions/us-central1/subnetworks/default" \
  --no-enable-intra-node-visibility \
  --default-max-pods-per-node "110" \
  --enable-ip-access \
  --security-posture=standard \
  --workload-vulnerability-scanning=disabled \
  --no-enable-master-authorized-networks \
  --no-enable-google-cloud-access \
  --addons HorizontalPodAutoscaling,HttpLoadBalancing,GcePersistentDiskCsiDriver \
  --enable-autoupgrade \
  --enable-autorepair \
  --max-surge-upgrade 1 \
  --max-unavailable-upgrade 0 \
  --binauthz-evaluation-mode=DISABLED \
  --enable-managed-prometheus \
  --enable-shielded-nodes \
  --node-locations "$ZONE"

# Deploy the application using Helm
sudo helm repo add vllm https://vllm-project.github.io/production-stack
sudo helm install vllm vllm/vllm-stack -f "$SETUP_YAML"
