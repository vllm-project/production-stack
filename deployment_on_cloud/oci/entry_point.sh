#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

# Configuration with defaults
OCI_PROFILE="${OCI_PROFILE:-DEFAULT}"
OCI_COMPARTMENT_ID="${OCI_COMPARTMENT_ID:-}"
OCI_REGION="${OCI_REGION:-us-ashburn-1}"
CLUSTER_NAME="${CLUSTER_NAME:-production-stack}"
KUBERNETES_VERSION="${KUBERNETES_VERSION:-v1.31.1}"

GPU_NODE_POOL_NAME="${GPU_NODE_POOL_NAME:-gpu-pool}"
GPU_NODE_COUNT="${GPU_NODE_COUNT:-1}"
GPU_SHAPE="${GPU_SHAPE:-VM.GPU.A10.1}"
GPU_IMAGE_ID="${GPU_IMAGE_ID:-}"  # Will be auto-detected if not set

# Private cluster mode (uses NAT Gateway + Bastion instead of public IPs)
PRIVATE_CLUSTER="${PRIVATE_CLUSTER:-true}"

# OCI CLI wrapper function to include profile and region
oci_cmd() {
    oci --profile "${OCI_PROFILE}" --region "${OCI_REGION}" "$@"
}

# Validate required environment variables
validate_env() {
    if [[ -z "${OCI_COMPARTMENT_ID}" ]]; then
        echo "Error: OCI_COMPARTMENT_ID environment variable is required"
        echo "Set it with: export OCI_COMPARTMENT_ID=ocid1.compartment.oc1..xxxxx"
        exit 1
    fi

    if ! command -v oci &> /dev/null; then
        echo "Error: OCI CLI is not installed"
        echo "Install from: https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/cliinstall.htm"
        exit 1
    fi

    if ! command -v jq &> /dev/null; then
        echo "Error: jq is not installed (required for JSON parsing)"
        echo "Install from: https://jqlang.github.io/jq/download/"
        exit 1
    fi

    if ! command -v kubectl &> /dev/null; then
        echo "Error: kubectl is not installed"
        echo "Install from: https://kubernetes.io/docs/tasks/tools/#kubectl"
        exit 1
    fi

    if ! command -v helm &> /dev/null; then
        echo "Error: Helm is not installed"
        echo "Install from: https://helm.sh/docs/intro/install/"
        exit 1
    fi

    if ! oci_cmd iam region list &> /dev/null; then
        echo "Error: OCI CLI is not configured or profile '${OCI_PROFILE}' not found"
        echo "Run: oci setup config"
        exit 1
    fi
}

# Get VCN and subnet for OKE cluster
get_or_create_network() {
    echo "Checking for existing VCN..."

    # Try to find existing VCN
    VCN_ID=$(oci_cmd network vcn list \
        --compartment-id "${OCI_COMPARTMENT_ID}" \
        --display-name "${CLUSTER_NAME}-vcn" \
        --query "data[0].id" \
        --raw-output 2>/dev/null || echo "")

    if [[ -z "${VCN_ID}" || "${VCN_ID}" == "null" ]]; then
        echo "Creating VCN for OKE cluster..."
        VCN_ID=$(oci_cmd network vcn create \
            --compartment-id "${OCI_COMPARTMENT_ID}" \
            --display-name "${CLUSTER_NAME}-vcn" \
            --cidr-blocks '["10.0.0.0/16"]' \
            --dns-label "prodstack" \
            --query "data.id" \
            --raw-output)
        echo "Created VCN: ${VCN_ID}"

        # Create Internet Gateway (needed for NAT Gateway and public LB subnet)
        echo "Creating Internet Gateway..."
        IGW_ID=$(oci_cmd network internet-gateway create \
            --compartment-id "${OCI_COMPARTMENT_ID}" \
            --vcn-id "${VCN_ID}" \
            --display-name "${CLUSTER_NAME}-igw" \
            --is-enabled true \
            --query "data.id" \
            --raw-output)

        if [[ "${PRIVATE_CLUSTER}" == "true" ]]; then
            # Create NAT Gateway for private subnets
            echo "Creating NAT Gateway (for private cluster)..."
            NAT_ID=$(oci_cmd network nat-gateway create \
                --compartment-id "${OCI_COMPARTMENT_ID}" \
                --vcn-id "${VCN_ID}" \
                --display-name "${CLUSTER_NAME}-nat" \
                --query "data.id" \
                --raw-output)

            # Create private route table (uses NAT Gateway)
            echo "Creating Private Route Table..."
            PRIVATE_RT_ID=$(oci_cmd network route-table create \
                --compartment-id "${OCI_COMPARTMENT_ID}" \
                --vcn-id "${VCN_ID}" \
                --display-name "${CLUSTER_NAME}-private-rt" \
                --route-rules "[{\"cidrBlock\": \"0.0.0.0/0\", \"networkEntityId\": \"${NAT_ID}\"}]" \
                --query "data.id" \
                --raw-output)

            # Create public route table (uses IGW) for LB subnet
            echo "Creating Public Route Table..."
            PUBLIC_RT_ID=$(oci_cmd network route-table create \
                --compartment-id "${OCI_COMPARTMENT_ID}" \
                --vcn-id "${VCN_ID}" \
                --display-name "${CLUSTER_NAME}-public-rt" \
                --route-rules "[{\"cidrBlock\": \"0.0.0.0/0\", \"networkEntityId\": \"${IGW_ID}\"}]" \
                --query "data.id" \
                --raw-output)

            RT_ID="${PRIVATE_RT_ID}"
        else
            # Create Route Table (public)
            echo "Creating Route Table..."
            RT_ID=$(oci_cmd network route-table create \
                --compartment-id "${OCI_COMPARTMENT_ID}" \
                --vcn-id "${VCN_ID}" \
                --display-name "${CLUSTER_NAME}-rt" \
                --route-rules "[{\"cidrBlock\": \"0.0.0.0/0\", \"networkEntityId\": \"${IGW_ID}\"}]" \
                --query "data.id" \
                --raw-output)
            PUBLIC_RT_ID="${RT_ID}"
        fi

        # Create Security List
        echo "Creating Security List..."
        SL_ID=$(oci_cmd network security-list create \
            --compartment-id "${OCI_COMPARTMENT_ID}" \
            --vcn-id "${VCN_ID}" \
            --display-name "${CLUSTER_NAME}-sl" \
            --egress-security-rules '[{"destination": "0.0.0.0/0", "protocol": "all", "isStateless": false}]' \
            --ingress-security-rules '[{"source": "0.0.0.0/0", "protocol": "6", "isStateless": false, "tcpOptions": {"destinationPortRange": {"min": 22, "max": 22}}}, {"source": "10.0.0.0/16", "protocol": "all", "isStateless": false}]' \
            --query "data.id" \
            --raw-output)

        # Create Subnet for worker nodes (private in private mode)
        echo "Creating Worker Subnet..."
        WORKER_SUBNET_ID=$(oci_cmd network subnet create \
            --compartment-id "${OCI_COMPARTMENT_ID}" \
            --vcn-id "${VCN_ID}" \
            --display-name "${CLUSTER_NAME}-worker-subnet" \
            --cidr-block "10.0.10.0/24" \
            --route-table-id "${RT_ID}" \
            --security-list-ids "[\"${SL_ID}\"]" \
            --dns-label "workers" \
            --prohibit-public-ip-on-vnic "${PRIVATE_CLUSTER}" \
            --query "data.id" \
            --raw-output)

        # Create Subnet for load balancers (public for external access)
        echo "Creating Load Balancer Subnet..."
        LB_SUBNET_ID=$(oci_cmd network subnet create \
            --compartment-id "${OCI_COMPARTMENT_ID}" \
            --vcn-id "${VCN_ID}" \
            --display-name "${CLUSTER_NAME}-lb-subnet" \
            --cidr-block "10.0.20.0/24" \
            --route-table-id "${PUBLIC_RT_ID:-$RT_ID}" \
            --security-list-ids "[\"${SL_ID}\"]" \
            --dns-label "loadbalancers" \
            --query "data.id" \
            --raw-output)

        # Create Subnet for Kubernetes API endpoint (private in private mode)
        echo "Creating API Endpoint Subnet..."
        API_SUBNET_ID=$(oci_cmd network subnet create \
            --compartment-id "${OCI_COMPARTMENT_ID}" \
            --vcn-id "${VCN_ID}" \
            --display-name "${CLUSTER_NAME}-api-subnet" \
            --cidr-block "10.0.0.0/28" \
            --route-table-id "${RT_ID}" \
            --security-list-ids "[\"${SL_ID}\"]" \
            --dns-label "kubeapi" \
            --prohibit-public-ip-on-vnic "${PRIVATE_CLUSTER}" \
            --query "data.id" \
            --raw-output)

        # Create Bastion subnet if private cluster
        if [[ "${PRIVATE_CLUSTER}" == "true" ]]; then
            echo "Creating Bastion Subnet..."
            BASTION_SUBNET_ID=$(oci_cmd network subnet create \
                --compartment-id "${OCI_COMPARTMENT_ID}" \
                --vcn-id "${VCN_ID}" \
                --display-name "${CLUSTER_NAME}-bastion-subnet" \
                --cidr-block "10.0.30.0/24" \
                --route-table-id "${PUBLIC_RT_ID}" \
                --security-list-ids "[\"${SL_ID}\"]" \
                --dns-label "bastion" \
                --query "data.id" \
                --raw-output)
        fi
    else
        echo "Using existing VCN: ${VCN_ID}"
        WORKER_SUBNET_ID=$(oci_cmd network subnet list \
            --compartment-id "${OCI_COMPARTMENT_ID}" \
            --vcn-id "${VCN_ID}" \
            --display-name "${CLUSTER_NAME}-worker-subnet" \
            --query "data[0].id" \
            --raw-output)
        LB_SUBNET_ID=$(oci_cmd network subnet list \
            --compartment-id "${OCI_COMPARTMENT_ID}" \
            --vcn-id "${VCN_ID}" \
            --display-name "${CLUSTER_NAME}-lb-subnet" \
            --query "data[0].id" \
            --raw-output)
        API_SUBNET_ID=$(oci_cmd network subnet list \
            --compartment-id "${OCI_COMPARTMENT_ID}" \
            --vcn-id "${VCN_ID}" \
            --display-name "${CLUSTER_NAME}-api-subnet" \
            --query "data[0].id" \
            --raw-output)
        BASTION_SUBNET_ID=$(oci_cmd network subnet list \
            --compartment-id "${OCI_COMPARTMENT_ID}" \
            --vcn-id "${VCN_ID}" \
            --display-name "${CLUSTER_NAME}-bastion-subnet" \
            --query "data[0].id" \
            --raw-output 2>/dev/null || echo "")
    fi
}

# Get GPU-compatible image
get_gpu_image() {
    if [[ -n "${GPU_IMAGE_ID}" ]]; then
        echo "${GPU_IMAGE_ID}"
        return
    fi

    # Get Oracle Linux GPU image for OKE
    oci_cmd compute image list \
        --compartment-id "${OCI_COMPARTMENT_ID}" \
        --operating-system "Oracle Linux" \
        --shape "${GPU_SHAPE}" \
        --sort-by TIMECREATED \
        --sort-order DESC \
        --query "data[?contains(\"display-name\", 'GPU')].id | [0]" \
        --raw-output
}

# Create OKE cluster
deploy_oke() {
    echo "Creating OKE cluster: ${CLUSTER_NAME}"

    get_or_create_network

    # Check if cluster already exists
    EXISTING_CLUSTER=$(oci_cmd ce cluster list \
        --compartment-id "${OCI_COMPARTMENT_ID}" \
        --name "${CLUSTER_NAME}" \
        --lifecycle-state ACTIVE \
        --query "data[0].id" \
        --raw-output 2>/dev/null || echo "")

    if [[ -n "${EXISTING_CLUSTER}" && "${EXISTING_CLUSTER}" != "null" ]]; then
        echo "Cluster already exists: ${EXISTING_CLUSTER}"
        CLUSTER_ID="${EXISTING_CLUSTER}"
    else
        # Determine public IP setting based on PRIVATE_CLUSTER
        if [[ "${PRIVATE_CLUSTER}" == "true" ]]; then
            ENDPOINT_PUBLIC_IP="false"
            echo "Creating new PRIVATE OKE cluster (no public IP)..."
        else
            ENDPOINT_PUBLIC_IP="true"
            echo "Creating new OKE cluster with public endpoint..."
        fi

        # Create cluster
        echo "Submitting cluster creation request..."
        CREATE_RESPONSE=$(oci_cmd ce cluster create \
            --compartment-id "${OCI_COMPARTMENT_ID}" \
            --name "${CLUSTER_NAME}" \
            --vcn-id "${VCN_ID}" \
            --kubernetes-version "${KUBERNETES_VERSION}" \
            --endpoint-subnet-id "${API_SUBNET_ID}" \
            --service-lb-subnet-ids "[\"${LB_SUBNET_ID}\"]" \
            --endpoint-public-ip-enabled "${ENDPOINT_PUBLIC_IP}" 2>&1) || true

        # Get cluster ID by listing clusters (with retry)
        echo "Retrieving cluster ID..."
        CLUSTER_ID=""
        for i in {1..10}; do
            sleep 5
            CLUSTER_JSON=$(oci_cmd ce cluster list \
                --compartment-id "${OCI_COMPARTMENT_ID}" \
                --name "${CLUSTER_NAME}" \
                --query "data[?\"lifecycle-state\"!='DELETED']" 2>/dev/null || echo "[]")

            CLUSTER_ID=$(echo "${CLUSTER_JSON}" | jq -r '.[0].id // empty' 2>/dev/null || echo "")

            if [[ -n "${CLUSTER_ID}" ]]; then
                echo "Found cluster: ${CLUSTER_ID}"
                break
            fi
            echo "  Attempt ${i}/10: Waiting for cluster to appear..."
        done

        if [[ -z "${CLUSTER_ID}" ]]; then
            echo "Error: Failed to create cluster or retrieve cluster ID"
            echo "Create response: ${CREATE_RESPONSE}"
            exit 1
        fi

        echo "Cluster ID: ${CLUSTER_ID}"
        echo "Waiting for cluster to become ACTIVE (this may take 10-15 minutes)..."
        while true; do
            STATE=$(oci_cmd ce cluster get --cluster-id "${CLUSTER_ID}" --query "data.\"lifecycle-state\"" --raw-output)
            echo "  Cluster state: ${STATE}"
            if [[ "${STATE}" == "ACTIVE" ]]; then
                echo "Cluster is now ACTIVE!"
                break
            elif [[ "${STATE}" == "FAILED" ]]; then
                echo "Error: Cluster creation failed!"
                # Get error details
                WR_ID=$(oci_cmd ce work-request list --compartment-id "${OCI_COMPARTMENT_ID}" --cluster-id "${CLUSTER_ID}" --query "data[0].id" --raw-output 2>/dev/null || echo "")
                if [[ -n "${WR_ID}" && "${WR_ID}" != "null" ]]; then
                    echo "Error details:"
                    oci_cmd ce work-request-log-entry list --compartment-id "${OCI_COMPARTMENT_ID}" --work-request-id "${WR_ID}" --query "data[*].message" 2>/dev/null || true
                fi
                exit 1
            fi
            sleep 30
        done
    fi

    echo "Cluster ID: ${CLUSTER_ID}"

    # Create Bastion for private cluster
    if [[ "${PRIVATE_CLUSTER}" == "true" ]]; then
        create_bastion
    fi
}

# Create OCI Bastion for private cluster access
create_bastion() {
    echo "Creating OCI Bastion for private cluster access..."

    # Check if bastion already exists
    EXISTING_BASTION=$(oci_cmd bastion bastion list \
        --compartment-id "${OCI_COMPARTMENT_ID}" \
        --bastion-lifecycle-state ACTIVE \
        --query "data[?name=='${CLUSTER_NAME}-bastion'].id | [0]" \
        --raw-output 2>/dev/null || echo "")

    if [[ -n "${EXISTING_BASTION}" && "${EXISTING_BASTION}" != "null" ]]; then
        echo "Bastion already exists: ${EXISTING_BASTION}"
        BASTION_ID="${EXISTING_BASTION}"
    else
        BASTION_ID=$(oci_cmd bastion bastion create \
            --compartment-id "${OCI_COMPARTMENT_ID}" \
            --bastion-type STANDARD \
            --target-subnet-id "${BASTION_SUBNET_ID}" \
            --name "${CLUSTER_NAME}-bastion" \
            --client-cidr-list '["0.0.0.0/0"]' \
            --query "data.id" \
            --raw-output)

        echo "Waiting for Bastion to become ACTIVE..."
        while true; do
            STATE=$(oci_cmd bastion bastion get --bastion-id "${BASTION_ID}" --query "data.\"lifecycle-state\"" --raw-output)
            echo "  Bastion state: ${STATE}"
            if [[ "${STATE}" == "ACTIVE" ]]; then
                echo "Bastion is now ACTIVE!"
                break
            elif [[ "${STATE}" == "FAILED" ]]; then
                echo "Warning: Bastion creation failed, continuing without bastion"
                BASTION_ID=""
                break
            fi
            sleep 10
        done
    fi
}

# Add GPU node pool
add_gpu_nodepool() {
    echo "Adding GPU node pool: ${GPU_NODE_POOL_NAME}"

    # Check if node pool already exists
    EXISTING_POOL=$(oci_cmd ce node-pool list \
        --compartment-id "${OCI_COMPARTMENT_ID}" \
        --cluster-id "${CLUSTER_ID}" \
        --name "${GPU_NODE_POOL_NAME}" \
        --query "data[0].id" \
        --raw-output 2>/dev/null || echo "")

    if [[ -n "${EXISTING_POOL}" && "${EXISTING_POOL}" != "null" ]]; then
        echo "GPU node pool already exists: ${EXISTING_POOL}"
        return
    fi

    # Get availability domain
    AD=$(oci_cmd iam availability-domain list \
        --compartment-id "${OCI_COMPARTMENT_ID}" \
        --query "data[0].name" \
        --raw-output)

    # Get GPU image
    GPU_IMAGE=$(get_gpu_image)

    echo "Creating GPU node pool with shape: ${GPU_SHAPE}"
    oci_cmd ce node-pool create \
        --compartment-id "${OCI_COMPARTMENT_ID}" \
        --cluster-id "${CLUSTER_ID}" \
        --name "${GPU_NODE_POOL_NAME}" \
        --kubernetes-version "${KUBERNETES_VERSION}" \
        --node-shape "${GPU_SHAPE}" \
        --node-image-id "${GPU_IMAGE}" \
        --size "${GPU_NODE_COUNT}" \
        --placement-configs "[{\"availabilityDomain\": \"${AD}\", \"subnetId\": \"${WORKER_SUBNET_ID}\"}]" \
        --node-metadata '{"user_data": ""}' \
        --initial-node-labels '[{"key": "app", "value": "gpu"}, {"key": "nvidia.com/gpu", "value": "true"}]'

    echo "Waiting for node pool to become ACTIVE..."
    sleep 60  # Give nodes time to provision
}

# Configure kubectl
configure_kubectl() {
    echo "Configuring kubectl..."

    if [[ "${PRIVATE_CLUSTER}" == "true" ]]; then
        # For private cluster, use PRIVATE_ENDPOINT
        oci_cmd ce cluster create-kubeconfig \
            --cluster-id "${CLUSTER_ID}" \
            --file "${HOME}/.kube/config" \
            --token-version 2.0.0 \
            --kube-endpoint PRIVATE_ENDPOINT

        # Fix kubeconfig for non-DEFAULT profiles
        if [[ "${OCI_PROFILE}" != "DEFAULT" ]]; then
            echo "Updating kubeconfig to use OCI profile: ${OCI_PROFILE}"
            KUBE_USER=$(kubectl config view -o jsonpath="{.contexts[?(@.name=='$(kubectl config current-context)')].context.user}" 2>/dev/null || echo "")
            if [[ -n "${KUBE_USER}" ]]; then
                # Add --profile argument to OCI exec auth
                kubectl config set-credentials "${KUBE_USER}" \
                    --exec-api-version=client.authentication.k8s.io/v1beta1 \
                    --exec-command=oci \
                    --exec-arg="--profile" \
                    --exec-arg="${OCI_PROFILE}" \
                    --exec-arg="ce" \
                    --exec-arg="cluster" \
                    --exec-arg="generate-token" \
                    --exec-arg="--cluster-id" \
                    --exec-arg="${CLUSTER_ID}" \
                    --exec-arg="--region" \
                    --exec-arg="${OCI_REGION}"
            fi
        fi

        # Get the private endpoint
        PRIVATE_ENDPOINT=$(oci_cmd ce cluster get --cluster-id "${CLUSTER_ID}" \
            --query "data.endpoints.\"private-endpoint\"" --raw-output)

        echo ""
        echo "=============================================="
        echo "PRIVATE CLUSTER - SSH TUNNEL REQUIRED"
        echo "=============================================="
        echo ""
        echo "Your cluster uses a private endpoint: ${PRIVATE_ENDPOINT}"
        echo ""
        echo "To access kubectl, create a bastion session and SSH tunnel:"
        echo ""
        echo "1. Create bastion session (run this command):"
        echo "   oci bastion session create-port-forwarding \\"
        echo "     --profile ${OCI_PROFILE} --region ${OCI_REGION} \\"
        echo "     --bastion-id ${BASTION_ID} \\"
        echo "     --target-private-ip ${PRIVATE_ENDPOINT%:*} \\"
        echo "     --target-port 6443 \\"
        echo "     --session-ttl 10800 \\"
        echo "     --display-name kubectl-tunnel"
        echo ""
        echo "2. Get SSH command from session, then run:"
        echo "   ssh -N -L 6443:${PRIVATE_ENDPOINT%:*}:6443 <session-ssh-command>"
        echo ""
        echo "3. Update kubeconfig to use localhost:"
        echo "   kubectl config set-cluster <cluster-name> --server=https://127.0.0.1:6443"
        echo ""
        echo "=============================================="
        echo ""
    else
        oci_cmd ce cluster create-kubeconfig \
            --cluster-id "${CLUSTER_ID}" \
            --file "${HOME}/.kube/config" \
            --token-version 2.0.0 \
            --kube-endpoint PUBLIC_ENDPOINT

        # Fix kubeconfig for non-DEFAULT profiles
        if [[ "${OCI_PROFILE}" != "DEFAULT" ]]; then
            echo "Updating kubeconfig to use OCI profile: ${OCI_PROFILE}"
            KUBE_USER=$(kubectl config view -o jsonpath="{.contexts[?(@.name=='$(kubectl config current-context)')].context.user}" 2>/dev/null || echo "")
            if [[ -n "${KUBE_USER}" ]]; then
                kubectl config set-credentials "${KUBE_USER}" \
                    --exec-api-version=client.authentication.k8s.io/v1beta1 \
                    --exec-command=oci \
                    --exec-arg="--profile" \
                    --exec-arg="${OCI_PROFILE}" \
                    --exec-arg="ce" \
                    --exec-arg="cluster" \
                    --exec-arg="generate-token" \
                    --exec-arg="--cluster-id" \
                    --exec-arg="${CLUSTER_ID}" \
                    --exec-arg="--region" \
                    --exec-arg="${OCI_REGION}"
            fi
        fi

        echo "Waiting for nodes to be ready..."
        kubectl wait --for=condition=Ready nodes --all --timeout=600s || true
        kubectl get nodes
    fi
}

# Install NVIDIA device plugin
install_nvidia_device_plugin() {
    echo "Installing NVIDIA device plugin..."
    kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.1/nvidia-device-plugin.yml

    echo "Waiting for NVIDIA device plugin to be ready..."
    kubectl -n kube-system wait --for=condition=Ready pods -l name=nvidia-device-plugin-ds --timeout=300s || true
}

# Apply OCI Block Storage StorageClass
apply_storage_class() {
    echo "Applying OCI Block Storage StorageClass..."
    kubectl apply -f "${SCRIPT_DIR}/oci-block-storage-sc.yaml"
}

# Deploy vLLM stack
deploy_vllm_stack() {
    echo "Deploying vLLM stack..."
    helm repo add vllm https://vllm-project.github.io/production-stack
    helm repo update

    HELM_VALUES_FLAG=""
    if [[ -n "${1:-}" ]]; then
        HELM_VALUES_FLAG="-f $1"
    else
        HELM_VALUES_FLAG="-f ${SCRIPT_DIR}/production_stack_specification.yaml"
    fi

    # shellcheck disable=SC2086
    helm upgrade -i \
        --wait \
        --timeout 10m \
        vllm \
        vllm/vllm-stack ${HELM_VALUES_FLAG}

    echo "Waiting for vLLM pods to be ready..."
    kubectl wait --for=condition=Ready pods -l app.kubernetes.io/name=vllm --timeout=600s || true
    kubectl get pods
}

# Cleanup resources
cleanup() {
    echo "Starting cleanup..."

    # Uninstall Helm release
    echo "Uninstalling vLLM Helm release..."
    helm uninstall vllm 2>/dev/null || true

    # Delete PVCs
    echo "Deleting PVCs..."
    kubectl delete pvc --all 2>/dev/null || true

    # Delete Bastions first
    echo "Deleting Bastions..."
    BASTION_JSON=$(oci_cmd bastion bastion list \
        --compartment-id "${OCI_COMPARTMENT_ID}" \
        --query "data[?starts_with(name, '${CLUSTER_NAME}')].id" 2>/dev/null || echo "[]")

    echo "${BASTION_JSON}" | jq -r '.[]?' 2>/dev/null | while read -r BASTION_ID; do
        if [[ -n "${BASTION_ID}" && "${BASTION_ID}" != "null" ]]; then
            echo "Deleting bastion: ${BASTION_ID}"
            oci_cmd bastion bastion delete --bastion-id "${BASTION_ID}" --force 2>/dev/null || true
        fi
    done

    # Get cluster ID (any state except DELETED)
    CLUSTER_JSON=$(oci_cmd ce cluster list \
        --compartment-id "${OCI_COMPARTMENT_ID}" \
        --name "${CLUSTER_NAME}" \
        --query "data[?\"lifecycle-state\"!='DELETED']" 2>/dev/null || echo "[]")

    CLUSTER_ID=$(echo "${CLUSTER_JSON}" | jq -r '.[0].id // empty' 2>/dev/null || echo "")

    if [[ -n "${CLUSTER_ID}" ]]; then
        echo "Found cluster: ${CLUSTER_ID}"

        # Delete node pools
        echo "Deleting node pools..."
        NODE_POOLS_JSON=$(oci_cmd ce node-pool list \
            --compartment-id "${OCI_COMPARTMENT_ID}" \
            --cluster-id "${CLUSTER_ID}" \
            --query "data[*].id" 2>/dev/null || echo "[]")

        echo "${NODE_POOLS_JSON}" | jq -r '.[]?' 2>/dev/null | while read -r POOL_ID; do
            if [[ -n "${POOL_ID}" ]]; then
                echo "Deleting node pool: ${POOL_ID}"
                oci_cmd ce node-pool delete --node-pool-id "${POOL_ID}" --force 2>/dev/null || true
            fi
        done

        # Wait for node pools to be deleted
        echo "Waiting for node pools to be deleted..."
        for i in {1..20}; do
            REMAINING=$(oci_cmd ce node-pool list \
                --compartment-id "${OCI_COMPARTMENT_ID}" \
                --cluster-id "${CLUSTER_ID}" \
                --query "length(data)" --raw-output 2>/dev/null || echo "0")
            if [[ "${REMAINING}" == "0" || -z "${REMAINING}" ]]; then
                echo "All node pools deleted."
                break
            fi
            echo "  Waiting for ${REMAINING} node pool(s) to be deleted..."
            sleep 30
        done

        # Delete cluster
        echo "Deleting OKE cluster: ${CLUSTER_ID}"
        oci_cmd ce cluster delete --cluster-id "${CLUSTER_ID}" --force 2>/dev/null || true

        # Poll for cluster deletion instead of fixed sleep
        echo "Waiting for cluster to be deleted..."
        for i in {1..40}; do
            STATE=$(oci_cmd ce cluster get --cluster-id "${CLUSTER_ID}" \
                --query "data.\"lifecycle-state\"" --raw-output 2>/dev/null || echo "DELETED")
            if [[ "${STATE}" == "DELETED" || "${STATE}" == "null" || -z "${STATE}" ]]; then
                echo "Cluster deleted."
                break
            fi
            echo "  Cluster state: ${STATE} (waiting...)"
            sleep 30
        done
    else
        echo "No active cluster found."
    fi

    # Get VCN ID
    VCN_ID=$(oci_cmd network vcn list \
        --compartment-id "${OCI_COMPARTMENT_ID}" \
        --display-name "${CLUSTER_NAME}-vcn" \
        --query "data[0].id" \
        --raw-output 2>/dev/null || echo "")

    if [[ -n "${VCN_ID}" && "${VCN_ID}" != "null" ]]; then
        echo "Cleaning up VCN resources: ${VCN_ID}"

        # Delete subnets first (with retry logic for dependencies)
        echo "Deleting subnets..."
        for attempt in {1..5}; do
            SUBNETS_JSON=$(oci_cmd network subnet list \
                --compartment-id "${OCI_COMPARTMENT_ID}" \
                --vcn-id "${VCN_ID}" \
                --query "data[*].id" 2>/dev/null || echo "[]")

            SUBNET_COUNT=$(echo "${SUBNETS_JSON}" | jq -r '.[]?' 2>/dev/null | wc -l | tr -d ' ')
            if [[ "${SUBNET_COUNT}" == "0" ]]; then
                echo "All subnets deleted."
                break
            fi

            echo "  Attempt ${attempt}/5: Deleting ${SUBNET_COUNT} subnet(s)..."
            echo "${SUBNETS_JSON}" | jq -r '.[]?' 2>/dev/null | while read -r SUBNET_ID; do
                if [[ -n "${SUBNET_ID}" ]]; then
                    echo "    Deleting subnet: ${SUBNET_ID}"
                    oci_cmd network subnet delete --subnet-id "${SUBNET_ID}" --force 2>/dev/null || true
                fi
            done

            echo "  Waiting for subnets to be deleted..."
            sleep 30
        done

        # Clear route table rules before deleting gateways
        echo "Clearing route table rules..."
        RT_JSON=$(oci_cmd network route-table list \
            --compartment-id "${OCI_COMPARTMENT_ID}" \
            --vcn-id "${VCN_ID}" \
            --query "data[*].id" 2>/dev/null || echo "[]")

        echo "${RT_JSON}" | jq -r '.[]?' 2>/dev/null | while read -r RT_ID; do
            if [[ -n "${RT_ID}" ]]; then
                echo "Clearing rules from route table: ${RT_ID}"
                oci_cmd network route-table update --rt-id "${RT_ID}" --route-rules '[]' --force 2>/dev/null || true
            fi
        done

        sleep 10

        # Delete NAT Gateway
        echo "Deleting NAT Gateway..."
        NAT_JSON=$(oci_cmd network nat-gateway list \
            --compartment-id "${OCI_COMPARTMENT_ID}" \
            --vcn-id "${VCN_ID}" \
            --query "data[*].id" 2>/dev/null || echo "[]")

        echo "${NAT_JSON}" | jq -r '.[]?' 2>/dev/null | while read -r NAT_ID; do
            if [[ -n "${NAT_ID}" ]]; then
                echo "Deleting NAT gateway: ${NAT_ID}"
                oci_cmd network nat-gateway delete --nat-gateway-id "${NAT_ID}" --force 2>/dev/null || true
            fi
        done

        # Delete Internet Gateway
        echo "Deleting Internet Gateway..."
        IGW_JSON=$(oci_cmd network internet-gateway list \
            --compartment-id "${OCI_COMPARTMENT_ID}" \
            --vcn-id "${VCN_ID}" \
            --query "data[*].id" 2>/dev/null || echo "[]")

        echo "${IGW_JSON}" | jq -r '.[]?' 2>/dev/null | while read -r IGW_ID; do
            if [[ -n "${IGW_ID}" ]]; then
                echo "Deleting internet gateway: ${IGW_ID}"
                oci_cmd network internet-gateway delete --ig-id "${IGW_ID}" --force 2>/dev/null || true
            fi
        done

        sleep 30

        # Delete non-default route tables
        echo "Deleting route tables..."
        echo "${RT_JSON}" | jq -r '.[]?' 2>/dev/null | while read -r RT_ID; do
            if [[ -n "${RT_ID}" ]]; then
                echo "Deleting route table: ${RT_ID}"
                oci_cmd network route-table delete --rt-id "${RT_ID}" --force 2>/dev/null || true
            fi
        done

        # Delete non-default security lists
        echo "Deleting security lists..."
        SL_JSON=$(oci_cmd network security-list list \
            --compartment-id "${OCI_COMPARTMENT_ID}" \
            --vcn-id "${VCN_ID}" \
            --query "data[?!contains(\"display-name\", 'Default')].id" 2>/dev/null || echo "[]")

        echo "${SL_JSON}" | jq -r '.[]?' 2>/dev/null | while read -r SL_ID; do
            if [[ -n "${SL_ID}" ]]; then
                echo "Deleting security list: ${SL_ID}"
                oci_cmd network security-list delete --security-list-id "${SL_ID}" --force 2>/dev/null || true
            fi
        done

        sleep 30

        # Delete VCN
        echo "Deleting VCN: ${VCN_ID}"
        oci_cmd network vcn delete --vcn-id "${VCN_ID}" --force 2>/dev/null || true
    else
        echo "No VCN found."
    fi

    echo "Cleanup completed!"
}

# Main
PARAM="${1:-err}"
case $PARAM in
setup)
    validate_env
    deploy_oke
    add_gpu_nodepool
    configure_kubectl
    if [[ "${PRIVATE_CLUSTER}" == "true" ]]; then
        echo ""
        echo "=============================================="
        echo "PRIVATE CLUSTER SETUP COMPLETE"
        echo "=============================================="
        echo ""
        echo "Infrastructure created successfully!"
        echo "To complete the deployment, establish SSH tunnel first, then run:"
        echo ""
        echo "  # After SSH tunnel is active:"
        echo "  kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.1/nvidia-device-plugin.yml"
        echo "  kubectl apply -f ${SCRIPT_DIR}/oci-block-storage-sc.yaml"
        echo "  helm repo add vllm https://vllm-project.github.io/production-stack"
        echo "  helm repo update"
        echo "  helm upgrade -i --wait vllm vllm/vllm-stack -f ${2:-${SCRIPT_DIR}/production_stack_specification.yaml}"
        echo ""
    else
        install_nvidia_device_plugin
        apply_storage_class
        deploy_vllm_stack "${2:-}"
        echo ""
        echo "Setup complete! Your vLLM stack is ready."
        echo "Check pods with: kubectl get pods"
        echo "Get service endpoint: kubectl get svc"
    fi
    ;;
cleanup)
    validate_env
    cleanup
    ;;
*)
    echo "Usage: $0 <setup|cleanup> [HELM_VALUES_FILE]"
    echo ""
    echo "Environment variables:"
    echo "  OCI_PROFILE         - OCI CLI profile (default: DEFAULT)"
    echo "  OCI_COMPARTMENT_ID  - Required: OCI compartment OCID"
    echo "  OCI_REGION          - OCI region (default: us-ashburn-1)"
    echo "  CLUSTER_NAME        - Cluster name (default: production-stack)"
    echo "  GPU_SHAPE           - GPU shape (default: VM.GPU.A10.1)"
    echo "  PRIVATE_CLUSTER     - Use private endpoint + bastion (default: true)"
    echo "  GPU_NODE_COUNT      - Number of GPU nodes (default: 1)"
    exit 1
    ;;
esac
