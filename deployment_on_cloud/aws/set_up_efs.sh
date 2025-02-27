#!/bin/bash
set -e  # Exit on error
set -o pipefail  # Exit on first command failure in a pipeline

CLUSTER_NAME=$1
REGION=$2
EFS_NAME="efs_for_eks"

# Fetch VPC ID
VPC_ID=$(aws eks describe-cluster --name "$CLUSTER_NAME" --query "cluster.resourcesVpcConfig.vpcId" --output text)

# Fetch Subnet IDs
read -r -a SUBNET_IDS <<< "$(aws eks describe-cluster --name "$CLUSTER_NAME" --query "cluster.resourcesVpcConfig.subnetIds" --output text)"

# Fetch Security Group used by EKS
INSTANCE_ID=$(aws ec2 describe-instances --filters Name=tag:eks:cluster-name,Values="$CLUSTER_NAME" --query "Reservations[*].Instances[*].InstanceId" --output text | head -n 1)
EKS_SG_ID=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --query "Reservations[0].Instances[0].SecurityGroups[*].GroupId" --output text)
echo "EKS Security Group ID: $EKS_SG_ID"

# Create Security Group for EFS
EFS_SG_ID=$(aws ec2 create-security-group \
    --group-name efs-sg \
    --description "Allow NFS from EKS" \
    --vpc-id "$VPC_ID" \
    --query "GroupId" --output text --region "$REGION")
echo "Created Security Group for EFS: $EFS_SG_ID"

# Allow NFS traffic (port 2049) from EKS nodes
aws ec2 authorize-security-group-ingress \
    --group-id "$EFS_SG_ID" \
    --protocol tcp \
    --port 2049 \
    --source-group "$EKS_SG_ID"

echo "Security group updated to allow NFS traffic."

# Create EFS File System
EFS_ID=$(aws efs create-file-system \
    --region "$REGION" \
    --performance-mode generalPurpose \
    --throughput-mode bursting \
    --tags Key=Name,Value="$EFS_NAME" \
    --query "FileSystemId" --output text)

echo "Created EFS File System: $EFS_ID"

# Wait for EFS to be available
echo "Waiting for EFS to become available..."
while true; do
    STATE=$(aws efs describe-file-systems --file-system-id "$EFS_ID" --query "FileSystems[0].LifeCycleState" --output text)
    echo "Current EFS state: $STATE"

    if [[ "$STATE" == "available" ]]; then
        echo "EFS is now available!"
        break
    fi

    echo "Waiting for EFS to become available..."
    sleep 10  # Wait 10 seconds before checking again
done

# Create Mount Targets in each subnet
for SUBNET_ID in "${SUBNET_IDS[@]}"; do
    echo "Creating mount target in subnet: $SUBNET_ID"
    aws efs create-mount-target \
        --file-system-id "$EFS_ID" \
        --subnet-id "$SUBNET_ID" \
        --security-groups "$EFS_SG_ID"
done

echo "EFS setup complete!"
echo "File System ID: $EFS_ID"
echo "$EFS_ID" > temp.txt
