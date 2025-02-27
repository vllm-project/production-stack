# Deploying vLLM production-stack on AWS EKS

This guide walks you through the script that sets up a vLLM production-stack on top of EKS on AWS. It includes how the script configures Elastic File System (EFS) for persistent volume, setting the security groups, and deploying a production AI inference stack using Helm.

## Installing Prerequisites

Before running this setup, ensure you have:

1. AWS CLI (version higher than v2) installed and configured with credential and region [[Link]](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
2. AWS eksctl [[Link]](https://eksctl.io/installation/)
3. Kubectl and Helm [[Link]](https://github.com/vllm-project/production-stack/blob/main/tutorials/00-install-kubernetes-env.md)

## TLDR

Disclaimer: This script requires GPU resources and will incur costs. Please make sure all resources are shut down properly.

To run the service, go into the "deployment_on_cloud/aws" folder and run:

```bash
bash entry_point.sh YOUR_AWSREGION EXAMPLE_YAML_PATH
```

Clean up the service (not including VPC) with:

```bash
bash clean_up.sh production-stack YOUR_AWSREGION
```

## Step by Step Explanation

### Step 1: Deploy the EKS Cluster

Create an Amazon EKS cluster with GPU-enabled nodes.

```bash
AWS_REGION=$1
SETUP_YAML=$2
CLUSTER_NAME="production-stack"

eksctl create cluster \
  --name "$CLUSTER_NAME" \
  --region "$AWS_REGION" \
  --version 1.27 \
  --nodegroup-name gpu-nodegroup \
  --node-type g6e.4xlarge \
  --nodes 2 \
  --nodes-min 2 \
  --nodes-max 2 \
  --managed
```

### Step 2: Set Up Amazon EFS for Persistent Volume

We use EFS as the persistent volume in EKS

```bash
CLUSTER_NAME=$1
REGION=$2
EFS_NAME="efs_for_eks"

## Fetch VPC ID
VPC_ID=$(aws eks describe-cluster --name "$CLUSTER_NAME" --query "cluster.resourcesVpcConfig.vpcId" --output text)
echo "VPC ID: $VPC_ID"

## Fetch Subnet IDs
SUBNET_IDS=($(aws eks describe-cluster --name "$CLUSTER_NAME" --query "cluster.resourcesVpcConfig.subnetIds" --output text))
echo "Subnets: ${SUBNET_IDS[@]}"

## Fetch Security Group used by EKS
INSTANCE_ID=$(aws ec2 describe-instances --filters Name=tag:eks:cluster-name,Values="$CLUSTER_NAME" --query "Reservations[*].Instances[*].InstanceId" --output text | head -n 1)
EKS_SG_ID=$(aws ec2 describe-instances --instance-ids $INSTANCE_ID --query "Reservations[0].Instances[0].SecurityGroups[*].GroupId" --output text)
echo "EKS Security Group ID: $EKS_SG_ID"

## Create Security Group for EFS
EFS_SG_ID=$(aws ec2 create-security-group \
    --group-name efs-sg \
    --description "Allow NFS from EKS" \
    --vpc-id "$VPC_ID" \
    --query "GroupId" --output text --region $REGION)
echo "Created Security Group for EFS: $EFS_SG_ID"

## Allow NFS traffic (port 2049) from EKS nodes
aws ec2 authorize-security-group-ingress \
    --group-id "$EFS_SG_ID" \
    --protocol tcp \
    --port 2049 \
    --source-group "$EKS_SG_ID"

echo "Security group updated to allow NFS traffic."

## Create EFS File System
EFS_ID=$(aws efs create-file-system \
    --region "$REGION" \
    --performance-mode generalPurpose \
    --throughput-mode bursting \
    --tags Key=Name,Value="$EFS_NAME" \
    --query "FileSystemId" --output text)

echo "Created EFS File System: $EFS_ID"

## Wait for EFS to be available
echo "Waiting for EFS to become available..."
while true; do
    STATE=$(aws efs describe-file-systems --file-system-id $EFS_ID --query "FileSystems[0].LifeCycleState" --output text)
    echo "Current EFS state: $STATE"

    if [[ "$STATE" == "available" ]]; then
        echo "EFS is now available!"
        break
    fi

    echo "Waiting for EFS to become available..."
    sleep 10  ## Wait 10 seconds before checking again
done

## Create Mount Targets in each subnet
for SUBNET_ID in "${SUBNET_IDS[@]}"; do
    echo "Creating mount target in subnet: $SUBNET_ID"
    aws efs create-mount-target \
        --file-system-id "$EFS_ID" \
        --subnet-id "$SUBNET_ID" \
        --security-groups "$EFS_SG_ID"
done

echo "EFS setup complete!"
echo "File System ID: $EFS_ID"
echo "$EFS_ID" > temp.text
```

This script retrieves the VPC ID, subnets, and security groups associated with the EKS cluster to creates a new EFS file system in the same VPC. It also configures NFS traffic (port 2049) from EKS nodes and attaches mount targets in EKS subnets.

### Step 3: Deploy the EFS CSI Driver

Enable EFS CSI driver to integrate EFS with Kubernetes.

```bash
eksctl utils associate-iam-oidc-provider --region "$AWS_REGION" --cluster "$CLUSTER_NAME" --approve

kubectl apply -k "github.com/kubernetes-sigs/aws-efs-csi-driver/deploy/kubernetes/overlays/stable/ecr/?ref=release-1.6"

kubectl get pods -n kube-system | grep efs

eksctl create iamserviceaccount \
    --region "$AWS_REGION" \
    --name efs-csi-controller-sa \
    --namespace kube-system \
    --cluster "$CLUSTER_NAME" \
    --attach-policy-arn arn:aws:iam::aws:policy/service-role/AmazonEFSCSIDriverPolicy \
    --approve
```

### Step 4: Create a Persistent Volume (PV)

Create efs-pv.yaml with the correct EFS ID:

```bash
EFS_ID=$(cat temp.text)

cat <<EOF > efs-pv.yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: efs-pv
spec:
  capacity:
    storage: 40Gi
  volumeMode: Filesystem
  accessModes:
    - ReadWriteMany
  persistentVolumeReclaimPolicy: Retain
  csi:
    driver: efs.csi.aws.com
    volumeHandle: $EFS_ID
EOF
```

Then it applies the PV configuration to create a Persistent Volume for EKS to use.

```bash
kubectl apply -f efs-pv.yaml
kubectl get pv
```

This step should return:

```bash
NAME     CAPACITY   ACCESS MODES   RECLAIM POLICY   STATUS      CLAIM   STORAGECLASS   REASON   AGE
efs-pv   40Gi       RWX            Retain           Available                                   9m21s
```

### Step 6: Deploy the Production AI Stack

Add the Helm repository and deploy the AI inference stack.

```bash
helm repo add vllm https://vllm-project.github.io/production-stack
helm install vllm ./vllm-stack -f $SETUP_YAML
```

Here is an example YAML file for a cluster with two Llama-3.1-8B models.

```yaml
servingEngineSpec:
  runtimeClassName: ""
  modelSpec:
  - name: "llama8b"
    repository: "vllm/vllm-openai"
    tag: "latest"
    modelURL: "meta-llama/Llama-3.1-8B"

    replicaCount: 2

    requestCPU: 6
    requestMemory: "16Gi"
    requestGPU: 1
    hf_token: YOUR_HUGGING_FACE_TOKEN
    pvcStorage: "40Gi"
    pvcAccessMode:
      - ReadWriteMany
    storageClass: ""
```

### Step 7 Stopping the Helm Cluster

This uninstalls the production-stack and cleans PV.

```bash
helm uninstall vllm
kubectl delete pv efs-pv
```

If you want to start the deployment again, you can run

```bash
kubectl apply -f efs-pv.yaml
helm install vllm vllm/vllm-stack -f production_stack_specification.yaml
```

### Step 8: Cleanup AWS resources

This step cleans up EKS, mount-points, created security groups, EFS.

```bash
bash clean_up.sh "$CLUSTER_NAME" "$AWS_REGION"
```

You may also want to manually delete the VPC and clean up the cloud formation in the AWS Console.

## Summary

This tutorial covers:
✅ Creating an EKS cluster with GPU nodes
\
✅ Setting up Amazon EFS for persistent storage
\
✅ Deploying EFS CSI driver
\
✅ Creating Persistent Volumes
\
✅ Installing a production stack for vLLM inference with Helm

Now your AWS EKS production-stack is ready for large-scale AI model deployment 🚀!
