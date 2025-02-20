#!/bin/bash

# Set variables
CLUSTER_NAME=$1
REGION=$2

echo "Starting cleanup for EKS cluster: $CLUSTER_NAME in region: $REGION"

# Delete all namespaces except default, kube-system, kube-public
echo "Deleting all custom namespaces..."
kubectl get ns --no-headers | awk '{print $1}' | grep -vE '^(default|kube-system|kube-public)$' | xargs -r kubectl delete ns

# Delete all workloads
echo "Deleting all workloads..."
kubectl delete deployments,statefulsets,daemonsets,services,ingresses,configmaps,secrets,persistentvolumeclaims,jobs,cronjobs --all --all-namespaces
kubectl delete persistentvolumes --all

# Delete managed node groups (if any exist)
echo "Checking for managed node groups..."
NODEGROUPS=$(aws eks list-nodegroups --cluster-name "$CLUSTER_NAME" --region "$REGION" --query "nodegroups[]" --output text)
if [ -n "$NODEGROUPS" ]; then
  for NODEGROUP in $NODEGROUPS; do
    echo "Deleting node group: $NODEGROUP"
    aws eks delete-nodegroup --cluster-name "$CLUSTER_NAME" --nodegroup-name "$NODEGROUP" --region "$REGION"
    echo "Waiting for node group $NODEGROUP to be deleted..."
    aws eks wait nodegroup-deleted --cluster-name "$CLUSTER_NAME" --nodegroup-name "$NODEGROUP" --region "$REGION"
  done
else
  echo "No managed node groups found."
fi

# Delete self-managed EC2 instances
echo "Deleting self-managed nodes..."
INSTANCE_IDS=$(aws ec2 describe-instances --filters "Name=tag:eks:cluster-name,Values=$CLUSTER_NAME" --query "Reservations[].Instances[].InstanceId" --output text --region "$REGION")
if [ -n "$INSTANCE_IDS" ]; then
  aws ec2 terminate-instances --instance-ids "$INSTANCE_IDS" --region "$REGION"
  echo "Waiting for EC2 instances to terminate..."
  aws ec2 wait instance-terminated --instance-ids "$INSTANCE_IDS" --region "$REGION"
fi

# Delete associated load balancers
echo "Deleting load balancers..."
LB_ARNs=$(aws elbv2 describe-load-balancers --query "LoadBalancers[?contains(LoadBalancerName, '$CLUSTER_NAME')].LoadBalancerArn" --output text --region "$REGION")
for LB_ARN in $LB_ARNs; do
  aws elbv2 delete-load-balancer --load-balancer-arn "$LB_ARN" --region "$REGION"
  echo "Waiting for load balancer $LB_ARN to be deleted..."
  aws elbv2 wait load-balancers-deleted --load-balancer-arns "$LB_ARN" --region "$REGION"
done

# Delete target groups
echo "Deleting target groups..."
TG_ARNs=$(aws elbv2 describe-target-groups --query "TargetGroups[?contains(TargetGroupName, '$CLUSTER_NAME')].TargetGroupArn" --output text --region "$REGION")
for TG_ARN in $TG_ARNs; do
  aws elbv2 delete-target-group --target-group-arn "$TG_ARN" --region "$REGION"
done

# # Delete NAT Gateways
echo "Deleting NAT Gateways..."
NAT_GATEWAYS=$(aws ec2 describe-nat-gateways --filter "Name=tag:Name,Values=eksctl-${CLUSTER_NAME}-cluster/NATGateway" --query "NatGateways[].NatGatewayId" --output text --region "$REGION")
for NAT_ID in $NAT_GATEWAYS; do
  aws ec2 delete-nat-gateway --nat-gateway-id "$NAT_ID" --region "$REGION"
  echo "Waiting for NAT Gateway $NAT_ID to be deleted..."
  aws ec2 wait nat-gateway-deleted --nat-gateway-ids "$NAT_ID" --region "$REGION"
done

# Release Elastic IPs
echo "Releasing Elastic IPs..."
EIP_ALLOCS=$(aws ec2 describe-addresses --query "Addresses[?AssociationId==null].AllocationId" --output text --region "$REGION")
for EIP in $EIP_ALLOCS; do
  aws ec2 release-address --allocation-id "$EIP" --region "$REGION"
  echo "Released Elastic IP $EIP"
done

# Release EFS and the created security group
read -r fs_id < temp.txt
echo "Processing File System: $fs_id"

# Get the list of mount targets
mount_targets=$(aws efs describe-mount-targets --file-system-id "$fs_id" --query "MountTargets[*].MountTargetId" --output text)

# Delete each mount target
for mt_id in $mount_targets; do
    echo "Deleting Mount Target: $mt_id"
    aws efs delete-mount-target --mount-target-id "$mt_id"
done

# Wait for mount targets to be deleted (optional, prevents API conflicts)
while [[ -n $(aws efs describe-mount-targets --file-system-id "$fs_id" --query "MountTargets[*].MountTargetId" --output text) ]]; do
    echo "Waiting for mount targets to be deleted..."
    sleep 10
done

# Delete the file system
echo "Deleting File System: $fs_id"
aws efs delete-file-system --file-system-id "$fs_id"

for sg in $(aws ec2 describe-security-groups --filters "Name=group-name,Values=efs-sg" --query "SecurityGroups[*].GroupId" --output text); do

    echo "Deleting Security Group: $sg"
    for eni in $(aws ec2 describe-network-interfaces --filters "Name=group-id,Values=$sg" --query "NetworkInterfaces[*].NetworkInterfaceId" --output text); do
        echo "$eni"
        aws ec2 delete-network-interface --network-interface-id "$eni"
    done
    aws ec2 delete-security-group --group-id "$sg"
done

# Delete the EKS cluster
echo "Deleting EKS cluster..."
aws eks delete-cluster --name "$CLUSTER_NAME" --region "$REGION"
echo "Waiting for cluster $CLUSTER_NAME to be deleted..."
aws eks wait cluster-deleted --name "$CLUSTER_NAME" --region "$REGION"

# TODO
# Clean up VPC
# Delete CloudFormation Stackecho "Deleting CloudFormation stacks..."

echo "EKS cluster $CLUSTER_NAME cleanup completed successfully!"
