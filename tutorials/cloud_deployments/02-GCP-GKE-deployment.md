# Deploying vLLM production-stack on GCP GKE

This guide walks you through the script that sets up a vLLM production stack on Google Kubernetes Engine (GKE) on Google Cloud Platform (GCP). It includes configuring a GKE cluster, setting up persistent storage, and deploying the production AI inference stack using Helm.

## Installing Prerequisites

Before running this setup, ensure you have:

1. GCP CLI installed and configured with credential and region set up [[Link]](https://cloud.google.com/sdk/docs/install)
2. Kubectl
3. Helm

## TLDR

Disclaimer: This script requires cloud resources and will incur costs. Please make sure all resources are shut down properly.

To run the service, go to "deployment_on_cloud/gcp" and run:

```bash
sudo bash entry_point.sh YAML_FILE_PATH
```

Pods for the vllm deployment should transition to Ready and the Running state.

Expected output:

```plaintext
NAME                                            READY   STATUS    RESTARTS   AGE
vllm-deployment-router-69b7f9748d-xrkvn         1/1     Running   0          75s
vllm-opt125m-deployment-vllm-696c998c6f-mvhg4   1/1     Running   0          75s
```

Clean up the service with:

```bash
bash clean_up.sh production-stack
```

## Step by Step Explanation

### Step 1: Deploy the GKE Cluster

This step creates a GKE cluster with specified configurations.

#### 1.1 Define Variables

```bash
#!/bin/bash
CLUSTER_NAME="production-stack"
ZONE="us-central1-a"
GCP_PROJECT=$(gcloud config get-value project)
```

- **Cluster Name**: Set the desired name for your cluster.
- **Zone**: Define the zone where your cluster will be created.
- **Project ID**: Retrieve the current GCP project ID.

#### 1.2 Check Project ID

```bash
if [ -z "$GCP_PROJECT" ]; then
  echo "Error: No GCP project ID found. Please set your project with 'gcloud config set project <PROJECT_ID>'."
  exit 1
fi
```

- **Error Handling**: Ensure that a GCP project ID is set; otherwise, exit with an error message.

#### 1.3 Validate Input Parameters

```bash
if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <SETUP_YAML>"
  exit 1
fi

SETUP_YAML=$1
```

- **Parameter Check**: Ensure that a YAML configuration file is provided as an argument.

#### 1.4 Create the GKE Cluster

```bash
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
  --scopes "https://www.googleapis.com/auth/devstorage.read_only","https://www.googleapis.com/auth/logging.write","https://www.googleapis.com/auth/monitoring","https://www.googleapis.com/auth/servicecontrol","https://www.googleapis.com/auth/service.management.readonly","https://www.googleapis.com/auth/trace.append" \
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
```

- **Cluster Creation**: This command creates the GKE cluster with specified configurations, including machine type, disk type, and logging settings.

### Step 2: Deploy the Application Using Helm

After the cluster is created, the next step is to deploy the vLLM application using Helm.

```bash
sudo helm repo add vllm https://vllm-project.github.io/production-stack
```

- **Helm Repository**: This command adds the vLLM Helm repository to your local Helm setup.

#### 2.2 Install the Application

```bash
sudo helm install vllm vllm/vllm-stack -f "$SETUP_YAML"
```

- **Deployment**: This command installs the vLLM stack using the specified YAML configuration file, which contains the settings for the deployment.

### Step 3: Verify Deployment

After running the above commands, check the status of the pods to ensure they are running correctly.

```bash
kubectl get pods
```

- **Expected Output**: You should see output indicating that the pods are in the "Running" state.

### Step 4: Clean Up Resources

To clean up the resources created during the deployment, you can run the following script:

#### 4.1 Define Cleanup Script

```bash
#!/bin/bash

CLUSTER_NAME=$1
ZONE=$(gcloud container clusters list --filter="name=$CLUSTER_NAME" --format="value(location)")

if [ -z "$ZONE" ]; then
  echo "Cluster $CLUSTER_NAME not found."
  exit 1
fi

echo "Starting cleanup for GKE cluster: $CLUSTER_NAME in zone: $ZONE"

```

- **Initial Setup**: Define the cluster name and retrieve the zone.

#### 4.2 Check Cluster Status

```bash
CLUSTER_STATUS=$(gcloud container clusters describe "$CLUSTER_NAME" --zone "$ZONE" --format="value(status)")

if [ "$CLUSTER_STATUS" == "RUNNING" ]; then
  echo "Deleting all custom namespaces..."
```

- **Status Check**: Ensure the cluster is running before proceeding with deletions.

#### 4.3 Delete Namespaces and Workloads

```bash
  kubectl get ns --no-headers | awk '{print $1}' | grep -vE '^(default|kube-system|kube-public)' | xargs -r kubectl delete ns
  echo "Deleting all workloads..."
  kubectl delete deployments,statefulsets,daemonsets,services,ingresses,configmaps,secrets,persistentvolumeclaims,jobs,cronjobs --all --all-namespaces
  kubectl delete persistentvolumes --all
```

- **Namespace and Workload Deletion**: This command deletes all custom namespaces and workloads deployed in the GKE cluster.

#### 4.4 Cleanup Node Pools and Load Balancers

```bash
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

  echo "Deleting Load Balancers..."
  LB_NAMES=$(kubectl get services --all-namespaces -o jsonpath='{.items[?(@.spec.type=="LoadBalancer")].metadata.name}')
  for LB_NAME in $LB_NAMES; do
    kubectl delete service "$LB_NAME" --all-namespaces
  done

```

- **Node Pool and Load Balancer Cleanup**: This part checks for any node pools and load balancers associated with the cluster and deletes them.

#### 4.5 Delete the GKE Cluster

```bash
else
  echo "Cluster $CLUSTER_NAME is not running or has already been deleted."
fi

echo "Deleting GKE cluster..."
gcloud container clusters delete "$CLUSTER_NAME" --zone "$ZONE" --quiet

```

- **Cluster Deletion**: Finally, this command deletes the GKE cluster itself.

#### 4.6 Wait for Cluster Deletion

```bash
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

```

- **Deletion Confirmation**: This loop waits until the cluster deletion is confirmed.

## Summary

This tutorial covers:

✅ Creating a GKE cluster for vLLM deployment.

✅ Deploying the vLLM application using Helm.

✅ Cleaning up resources after deployment.

Now your GCP GKE production stack is ready for large-scale AI model deployment! 🚀
