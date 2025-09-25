#!/bin/bash

AWS_REGION=$1
SETUP_YAML=$2
CLUSTER_NAME="production-stack"
#This script assumes you have latest AWS cli logged in.

# Set up EKS cluster
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


# Create EFS (need to be in same VPC as EKS)
bash set_up_efs.sh "$CLUSTER_NAME" "$AWS_REGION"

# #Create CSI driver
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


#create pv after modify the filesys id to be the filesys id
#storage needed is based on model weights
EFS_ID=$(cat temp.txt)

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

kubectl apply -f efs-pv.yaml
kubectl get pv

#Now we start the production stack.
helm repo add vllm https://vllm-project.github.io/production-stack
helm install vllm vllm/vllm-stack -f "$SETUP_YAML"
