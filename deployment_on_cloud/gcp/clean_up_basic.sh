#!/bin/bash

# Set variables
CLUSTER_NAME=$1

# Automatically get the zone for the GKE cluster
ZONE=$(gcloud container clusters list --filter="name=$CLUSTER_NAME" --format="value(location)")

if [ -z "$ZONE" ]; then
  echo "Cluster $CLUSTER_NAME not found."
  exit 1
fi

echo "Starting cleanup for GKE cluster: $CLUSTER_NAME in zone: $ZONE"

# Check if the cluster is still active
CLUSTER_STATUS=$(gcloud container clusters describe "$CLUSTER_NAME" --zone "$ZONE" --format="value(status)")

if [ "$CLUSTER_STATUS" == "RUNNING" ]; then
  # Delete all namespaces except for default, kube-system, and kube-public
  echo "Deleting all custom namespaces..."
  kubectl get ns --no-headers | awk '{print $1}' | grep -vE '^(default|kube-system|kube-public)' | xargs -r kubectl delete ns

  # Delete all workloads
  echo "Deleting all workloads..."
  kubectl delete deployments,statefulsets,daemonsets,services,ingresses,configmaps,secrets,persistentvolumeclaims,jobs,cronjobs --all --all-namespaces
  kubectl delete persistentvolumes --all

  # Delete GKE node pools
  echo "Checking for node pools..."
  NODE_POOLS=$(gcloud container node-pools list --cluster "$CLUSTER_NAME" --zone "$ZONE" --format="value(name)")
  if [ -n "$NODE_POOLS" ]; then
    for NODE_POOL in $NODE_POOLS; do
      echo "Deleting node pool: $NODE_POOL"
      gcloud container node-pools delete "$NODE_POOL" --cluster "$CLUSTER_NAME" --zone "$ZONE" --quiet
    done
  else
    echo "No node pools found."
  fi

  # Delete Load Balancers
  echo "Deleting Load Balancers..."
  LB_NAMES=$(kubectl get services --all-namespaces -o jsonpath='{.items[?(@.spec.type=="LoadBalancer")].metadata.name}')
  for LB_NAME in $LB_NAMES; do
    kubectl delete service "$LB_NAME" --all-namespaces
  done
else
  echo "Cluster $CLUSTER_NAME is not running or has already been deleted."
fi

# Delete GKE cluster
echo "Deleting GKE cluster..."
gcloud container clusters delete "$CLUSTER_NAME" --zone "$ZONE" --quiet

# Wait for the cluster deletion to complete
echo "Waiting for cluster $CLUSTER_NAME to be deleted..."
while true; do
  sleep 10
  CLUSTER_STATUS=$(gcloud container clusters describe "$CLUSTER_NAME" --zone "$ZONE" --format="value(status)" 2>/dev/null)
  if [ "$CLUSTER_STATUS" == "DELETING" ]; then
    continue
  else
    break
  fi
done

echo "Cluster $CLUSTER_NAME deleted."

# Delete persistent disks
echo "Deleting persistent disks..."
DISK_NAMES=$(gcloud compute disks list --filter="name~'$CLUSTER_NAME' AND status='READY'" --format="value(name)")
for DISK_NAME in $DISK_NAMES; do
  gcloud compute disks delete "$DISK_NAME" --quiet
done

echo "GKE cluster $CLUSTER_NAME cleanup completed successfully!"
