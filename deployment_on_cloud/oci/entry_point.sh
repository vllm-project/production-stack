#!/usr/bin/env bash
#
# OCI OKE vLLM Deployment Script
#
# KEY LEARNINGS / GOTCHAS:
#
# 1. GPU NODE FILESYSTEM EXPANSION (CRITICAL):
#    - OCI boot volumes have a FIXED ~47GB partition regardless of the volume size
#    - Even with 200GB boot volume, OS only sees ~47GB until manually expanded
#    - Do NOT use cloud-init with oci-growfs - it breaks node registration (>20min timeout)
#    - Must expand filesystem AFTER the node joins using a privileged pod
#    - CRITICAL: Run disk expansion BEFORE vLLM deployment, as the vLLM image is ~10GB
#      and will cause DiskPressure on nodes with unexpanded filesystems
#
# 2. DISK EXPANSION STEPS (must be in this exact order):
#    a) growpart /dev/sda 3       - Expand partition 3 to use full disk (THIS IS THE KEY STEP!)
#    b) pvresize /dev/sda3        - Tell LVM the physical volume is larger
#    c) lvextend -l +100%FREE ... - Extend the logical volume
#    d) xfs_growfs /              - Grow XFS filesystem to fill the LV
#
#    IMPORTANT: Steps b-d do NOTHING if step a hasn't run first!
#    The partition must be expanded before LVM can use the space.
#
# 3. OCI-GROWFS ISSUES:
#    - oci-growfs can hang/timeout during LVM operations (not reliable)
#    - Don't rely on oci-growfs alone - always run growpart directly first
#    - The expand_gpu_disk() function handles all steps with proper verification
#
# 4. ROUTER OOM KILL:
#    - Default router memory (500Mi) is too low and causes OOMKill
#    - The fix_router_memory() function patches it to 1Gi after deployment
#    - Run: ./entry_point.sh fix-router
#
# 5. GPU AVAILABILITY DOMAIN:
#    - A10 GPUs are NOT available in all ADs - check before deployment
#    - us-ashburn-1: AD-2 and AD-3 (use GPU_AD_INDEX=1 or 2)
#    - us-chicago-1: AD-1 only (use GPU_AD_INDEX=0)
#    - Check with: oci compute shape list --availability-domain <AD> | grep GPU
#
# 6. BASTION SSH TUNNEL:
#    - Bastion sessions require SSH public key file (--ssh-public-key-file)
#    - Use ServerAliveInterval to keep tunnel alive: ssh -o ServerAliveInterval=30
#    - Tunnel format: ssh -i <key> -N -L 6443:<private-ip>:6443 <session>@host.bastion...
#    - IMPORTANT: After starting tunnel, update kubeconfig to use 127.0.0.1:6443
#
# 7. PRIVATE CLUSTER WORKFLOW:
#    a) Run: ./entry_point.sh setup
#    b) Create bastion session: oci bastion session create-port-forwarding ...
#    c) Start SSH tunnel in separate terminal (from the session output)
#    d) Update kubeconfig: kubectl config set-cluster $(kubectl config current-context) --server=https://127.0.0.1:6443
#    e) Verify: kubectl get nodes
#    f) Run: ./entry_point.sh deploy-vllm
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

# Configuration with defaults
OCI_PROFILE="${OCI_PROFILE:-DEFAULT}"
OCI_COMPARTMENT_ID="${OCI_COMPARTMENT_ID:-}"
OCI_REGION="${OCI_REGION:-us-ashburn-1}"
CLUSTER_NAME="${CLUSTER_NAME:-production-stack}"
# Note: Check OCI documentation for currently supported Kubernetes versions
# OKE GPU images have specific K8s version requirements (e.g., OKE-1.31.10)
# See: https://docs.oracle.com/en-us/iaas/Content/ContEng/Concepts/contengaboutk8sversions.htm
KUBERNETES_VERSION="${KUBERNETES_VERSION:-v1.31.10}"

GPU_NODE_POOL_NAME="${GPU_NODE_POOL_NAME:-gpu-pool}"
GPU_NODE_COUNT="${GPU_NODE_COUNT:-1}"
GPU_SHAPE="${GPU_SHAPE:-VM.GPU.A10.1}"
GPU_IMAGE_ID="${GPU_IMAGE_ID:-}"  # Will be auto-detected if not set
GPU_BOOT_VOLUME_GB="${GPU_BOOT_VOLUME_GB:-200}"  # 200GB for vLLM images + model weights

# Private cluster mode (uses NAT Gateway + Bastion instead of public IPs)
PRIVATE_CLUSTER="${PRIVATE_CLUSTER:-true}"

# Bastion client CIDR - restricts who can connect to the bastion
# SECURITY: Set this to your IP/CIDR (e.g., "YOUR_IP/32" or "CORP_NETWORK/24")
# Default 0.0.0.0/0 allows any IP but is less secure
BASTION_CLIENT_CIDR="${BASTION_CLIENT_CIDR:-0.0.0.0/0}"

# GPU Availability Domain index (0-based). GPU shapes may not be available in all ADs.
# Use 'oci compute shape list --availability-domain <AD>' to check availability.
# Default: 1 (second AD - Ashburn has A10 in AD-2 and AD-3)
GPU_AD_INDEX="${GPU_AD_INDEX:-1}"

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

        # Get the service CIDR for Oracle Services Network (needed for security list egress rules)
        SERVICE_ID=$(oci_cmd network service list \
            --query "data[?contains(\"cidr-block\", 'all') && contains(\"cidr-block\", 'services')].id | [0]" \
            --raw-output)
        SERVICE_CIDR=$(oci_cmd network service list \
            --query "data[?contains(\"cidr-block\", 'all') && contains(\"cidr-block\", 'services')].\"cidr-block\" | [0]" \
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

            # Create Service Gateway for Oracle Services Network access
            # This is required for OKE nodes to access OCIR, Object Storage, and other OCI services
            echo "Creating Service Gateway..."
            SGW_ID=$(oci_cmd network service-gateway create \
                --compartment-id "${OCI_COMPARTMENT_ID}" \
                --vcn-id "${VCN_ID}" \
                --display-name "${CLUSTER_NAME}-sgw" \
                --services "[{\"serviceId\": \"${SERVICE_ID}\"}]" \
                --query "data.id" \
                --raw-output)

            # Create private route table (uses NAT Gateway + Service Gateway)
            echo "Creating Private Route Table..."
            PRIVATE_RT_ID=$(oci_cmd network route-table create \
                --compartment-id "${OCI_COMPARTMENT_ID}" \
                --vcn-id "${VCN_ID}" \
                --display-name "${CLUSTER_NAME}-private-rt" \
                --route-rules "[{\"cidrBlock\": \"0.0.0.0/0\", \"networkEntityId\": \"${NAT_ID}\"}, {\"destination\": \"${SERVICE_CIDR}\", \"destinationType\": \"SERVICE_CIDR_BLOCK\", \"networkEntityId\": \"${SGW_ID}\"}]" \
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

        # Create Security List with OKE-required rules
        # Includes: SSH, VCN CIDR, Kubernetes pods CIDR, services CIDR, and ICMP for path MTU
        # Egress includes Oracle Services Network for OKE node registration
        echo "Creating Security List..."
        SL_ID=$(oci_cmd network security-list create \
            --compartment-id "${OCI_COMPARTMENT_ID}" \
            --vcn-id "${VCN_ID}" \
            --display-name "${CLUSTER_NAME}-sl" \
            --egress-security-rules "[{\"destination\": \"0.0.0.0/0\", \"protocol\": \"all\", \"isStateless\": false, \"description\": \"Internet via NAT\"}, {\"destination\": \"${SERVICE_CIDR}\", \"destinationType\": \"SERVICE_CIDR_BLOCK\", \"protocol\": \"6\", \"isStateless\": false, \"description\": \"Oracle Services via Service Gateway\"}]" \
            --ingress-security-rules '[
                {"source": "10.0.0.0/16", "protocol": "6", "isStateless": false, "tcpOptions": {"destinationPortRange": {"min": 22, "max": 22}}, "description": "SSH access from VCN only"},
                {"source": "10.0.0.0/16", "protocol": "all", "isStateless": false, "description": "VCN internal traffic"},
                {"source": "10.244.0.0/16", "protocol": "all", "isStateless": false, "description": "Kubernetes pods CIDR"},
                {"source": "10.96.0.0/16", "protocol": "all", "isStateless": false, "description": "Kubernetes services CIDR"},
                {"source": "0.0.0.0/0", "protocol": "1", "isStateless": false, "icmpOptions": {"type": 3, "code": 4}, "description": "Path MTU discovery"}
            ]' \
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

# Get GPU-compatible OKE image
# IMPORTANT: Must use OKE-specific images (contain "OKE" in name) which have kubelet pre-installed
# Regular GPU images don't have OKE components and nodes will fail to register
get_gpu_image() {
    if [[ -n "${GPU_IMAGE_ID}" ]]; then
        echo "${GPU_IMAGE_ID}"
        return
    fi

    # Extract full version without 'v' prefix (e.g., "v1.31.10" -> "1.31.10")
    local K8S_VERSION
    K8S_VERSION="${KUBERNETES_VERSION#v}"

    # Get OKE-specific GPU image from node-pool-options API
    # These images have kubelet and OKE node registration components pre-installed
    # Search for exact version match (e.g., OKE-1.31.10)
    local IMAGE_ID
    IMAGE_ID=$(oci_cmd ce node-pool-options get \
        --node-pool-option-id all \
        --compartment-id "${OCI_COMPARTMENT_ID}" \
        --query "data.sources[?contains(\"source-name\", 'GPU') && contains(\"source-name\", 'OKE-${K8S_VERSION}') && !contains(\"source-name\", 'aarch64')].\"image-id\" | [0]" \
        --raw-output 2>/dev/null)

    if [[ -n "${IMAGE_ID}" && "${IMAGE_ID}" != "null" ]]; then
        echo "${IMAGE_ID}"
        return
    fi

    # Fallback: try major.minor version match (e.g., OKE-1.31)
    local K8S_MAJOR_MINOR
    K8S_MAJOR_MINOR=$(echo "${K8S_VERSION}" | cut -d. -f1,2)
    IMAGE_ID=$(oci_cmd ce node-pool-options get \
        --node-pool-option-id all \
        --compartment-id "${OCI_COMPARTMENT_ID}" \
        --query "data.sources[?contains(\"source-name\", 'GPU') && contains(\"source-name\", 'OKE-${K8S_MAJOR_MINOR}') && !contains(\"source-name\", 'aarch64')].\"image-id\" | [0]" \
        --raw-output 2>/dev/null)

    if [[ -n "${IMAGE_ID}" && "${IMAGE_ID}" != "null" ]]; then
        # Warn that we're using a different patch version
        echo "WARNING: No OKE GPU image found for K8s ${K8S_VERSION}, using closest match" >&2
        echo "${IMAGE_ID}"
        return
    fi

    # Last fallback: try any OKE GPU image
    IMAGE_ID=$(oci_cmd ce node-pool-options get \
        --node-pool-option-id all \
        --compartment-id "${OCI_COMPARTMENT_ID}" \
        --query "data.sources[?contains(\"source-name\", 'GPU') && contains(\"source-name\", 'OKE') && !contains(\"source-name\", 'aarch64')].\"image-id\" | [0]" \
        --raw-output 2>/dev/null)

    if [[ -n "${IMAGE_ID}" && "${IMAGE_ID}" != "null" ]]; then
        echo "WARNING: No OKE GPU image found for K8s ${K8S_MAJOR_MINOR}.x, using available image" >&2
        echo "${IMAGE_ID}"
        return
    fi

    # Last resort: use compute image list (will likely fail for OKE registration)
    echo "ERROR: No OKE-specific GPU image found. Node registration will likely fail." >&2
    echo "Please check available OKE images with: oci ce node-pool-options get --node-pool-option-id all" >&2
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
        # Warn if using insecure default
        if [[ "${BASTION_CLIENT_CIDR}" == "0.0.0.0/0" ]]; then
            echo "WARNING: Bastion is configured to allow connections from any IP (0.0.0.0/0)"
            echo "         For production, set BASTION_CLIENT_CIDR to your IP/CIDR (e.g., 'x.x.x.x/32')"
        fi

        BASTION_ID=$(oci_cmd bastion bastion create \
            --compartment-id "${OCI_COMPARTMENT_ID}" \
            --bastion-type STANDARD \
            --target-subnet-id "${BASTION_SUBNET_ID}" \
            --name "${CLUSTER_NAME}-bastion" \
            --client-cidr-list "[\"${BASTION_CLIENT_CIDR}\"]" \
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

# Get CPU-compatible OKE image
get_cpu_image() {
    # Get OKE image for CPU nodes (non-GPU, non-ARM)
    local K8S_VERSION
    K8S_VERSION="${KUBERNETES_VERSION#v}"

    local IMAGE_ID
    IMAGE_ID=$(oci_cmd ce node-pool-options get \
        --node-pool-option-id all \
        --compartment-id "${OCI_COMPARTMENT_ID}" \
        --query "data.sources[?contains(\"source-name\", 'OKE-${K8S_VERSION}') && !contains(\"source-name\", 'GPU') && !contains(\"source-name\", 'aarch64') && !contains(\"source-name\", 'Gen2')].\"image-id\" | [0]" \
        --raw-output 2>/dev/null)

    if [[ -n "${IMAGE_ID}" && "${IMAGE_ID}" != "null" ]]; then
        echo "${IMAGE_ID}"
        return
    fi

    # Fallback to any non-GPU OKE image
    oci_cmd ce node-pool-options get \
        --node-pool-option-id all \
        --compartment-id "${OCI_COMPARTMENT_ID}" \
        --query "data.sources[?contains(\"source-name\", 'OKE') && !contains(\"source-name\", 'GPU') && !contains(\"source-name\", 'aarch64')].\"image-id\" | [0]" \
        --raw-output 2>/dev/null
}

# Add CPU node pool (required before GPU nodes for kube-system workloads)
# GPU nodes require CPU nodes to be active first for cluster bootstrapping
add_cpu_nodepool() {
    echo "Adding CPU node pool for kube-system workloads..."

    # Check if CPU node pool already exists
    EXISTING_CPU_POOL=$(oci_cmd ce node-pool list \
        --compartment-id "${OCI_COMPARTMENT_ID}" \
        --cluster-id "${CLUSTER_ID}" \
        --name "cpu-pool" \
        --query "data[0].id" \
        --raw-output 2>/dev/null || echo "")

    if [[ -n "${EXISTING_CPU_POOL}" && "${EXISTING_CPU_POOL}" != "null" ]]; then
        echo "CPU node pool already exists: ${EXISTING_CPU_POOL}"
        return
    fi

    # Get availability domain - use same AD as GPU (AD-2) for consistency
    AD=$(oci_cmd iam availability-domain list \
        --compartment-id "${OCI_COMPARTMENT_ID}" \
        --query "data[${GPU_AD_INDEX}].name" \
        --raw-output)
    echo "Using availability domain for CPU: ${AD}"

    # Get CPU image
    CPU_IMAGE=$(get_cpu_image)
    echo "Using CPU image: ${CPU_IMAGE}"

    echo "Creating CPU node pool with shape: VM.Standard.E5.Flex"
    oci_cmd ce node-pool create \
        --compartment-id "${OCI_COMPARTMENT_ID}" \
        --cluster-id "${CLUSTER_ID}" \
        --name "cpu-pool" \
        --kubernetes-version "${KUBERNETES_VERSION}" \
        --node-shape "VM.Standard.E5.Flex" \
        --node-shape-config '{"memoryInGBs": 16, "ocpus": 2}' \
        --node-image-id "${CPU_IMAGE}" \
        --size 1 \
        --placement-configs "[{\"availabilityDomain\": \"${AD}\", \"subnetId\": \"${WORKER_SUBNET_ID}\"}]"

    echo "Waiting for CPU node pool to become ACTIVE..."
    local CPU_POOL_ID
    CPU_POOL_ID=$(oci_cmd ce node-pool list \
        --compartment-id "${OCI_COMPARTMENT_ID}" \
        --cluster-id "${CLUSTER_ID}" \
        --name "cpu-pool" \
        --query "data[0].id" \
        --raw-output 2>/dev/null)

    local MAX_WAIT=20
    for i in $(seq 1 $MAX_WAIT); do
        NODE_STATE=$(oci_cmd ce node-pool get \
            --node-pool-id "${CPU_POOL_ID}" \
            --query 'data.nodes[0]."lifecycle-state"' \
            --raw-output 2>/dev/null || echo "UNKNOWN")

        echo "  CPU node state: ${NODE_STATE} (${i}/${MAX_WAIT})"

        if [[ "${NODE_STATE}" == "ACTIVE" ]]; then
            echo "CPU node pool is ready!"
            echo "Waiting 60 seconds for kube-system pods to initialize before creating GPU pool..."
            sleep 60
            return
        fi
        sleep 30
    done
    echo "Warning: CPU node pool did not become ACTIVE within expected time"
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

    # Get availability domain for GPU nodes (may differ from CPU nodes due to shape availability)
    AD=$(oci_cmd iam availability-domain list \
        --compartment-id "${OCI_COMPARTMENT_ID}" \
        --query "data[${GPU_AD_INDEX}].name" \
        --raw-output)
    echo "Using availability domain for GPU: ${AD}"

    # Get GPU image
    GPU_IMAGE=$(get_gpu_image)

    # NOTE: We do NOT use cloud-init here because it breaks node registration.
    # Instead, we expand the filesystem after the node joins using a privileged pod.
    # See expand_gpu_disk() function.

    echo "Creating GPU node pool with shape: ${GPU_SHAPE} (boot volume: ${GPU_BOOT_VOLUME_GB}GB)"
    oci_cmd ce node-pool create \
        --compartment-id "${OCI_COMPARTMENT_ID}" \
        --cluster-id "${CLUSTER_ID}" \
        --name "${GPU_NODE_POOL_NAME}" \
        --kubernetes-version "${KUBERNETES_VERSION}" \
        --node-shape "${GPU_SHAPE}" \
        --node-image-id "${GPU_IMAGE}" \
        --node-boot-volume-size-in-gbs "${GPU_BOOT_VOLUME_GB}" \
        --size "${GPU_NODE_COUNT}" \
        --placement-configs "[{\"availabilityDomain\": \"${AD}\", \"subnetId\": \"${WORKER_SUBNET_ID}\"}]" \
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
        echo "2. Find the 'ssh-command' in the output of the previous command and run it in a new terminal."
        echo "   It will look like: ssh -i <private_key> -N -L 6443:${PRIVATE_ENDPOINT%:*}:6443 ...@host.bastion..."
        echo ""
        echo "3. Update kubeconfig to use localhost:"
        echo "   kubectl config set-cluster \$(kubectl config current-context) --server=https://127.0.0.1:6443"
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

# Expand GPU node filesystem using privileged pod
#
# WHY THIS IS NEEDED:
# - OCI boot volumes have a fixed ~47GB partition regardless of the volume size you request
# - Even with a 200GB boot volume, the OS only sees ~47GB until the partition is expanded
# - Cloud-init with oci-growfs breaks OKE node registration (>20min timeout)
# - We cannot SSH directly to managed OKE nodes
#
# SOLUTION:
# Run filesystem expansion commands via a privileged pod after the node joins.
# The expansion has 4 steps that MUST run in order:
#   1. growpart - Expand partition 3 to use the full disk
#   2. pvresize - Tell LVM the physical volume is now larger
#   3. lvextend - Extend the logical volume to use the new space
#   4. xfs_growfs - Grow the XFS filesystem to fill the logical volume
#
# CRITICAL LEARNINGS:
# - oci-growfs can hang/timeout during LVM operations - don't rely on it alone
# - ALWAYS run growpart first to expand the partition (this is the key step!)
# - pvresize/lvextend do nothing if the partition wasn't expanded first
# - Must wait for each step to complete before moving to the next
# - Kubelet needs time after restart to report new allocatable storage
#
expand_gpu_disk() {
    echo "=============================================="
    echo "EXPANDING GPU NODE FILESYSTEM"
    echo "=============================================="
    echo ""

    # Get GPU node name
    local GPU_NODE
    GPU_NODE=$(kubectl get nodes -l app=gpu -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

    if [[ -z "${GPU_NODE}" ]]; then
        echo "Warning: No GPU node found with label app=gpu. Skipping disk expansion."
        return 0
    fi

    echo "Found GPU node: ${GPU_NODE}"

    # Check current filesystem size by running df on the node
    echo "Checking current filesystem size..."
    local CURRENT_SIZE_OUTPUT
    CURRENT_SIZE_OUTPUT=$(kubectl run check-disk-size --rm -i --restart=Never \
        --image=busybox:latest \
        --overrides="{\"spec\":{\"nodeName\":\"${GPU_NODE}\",\"tolerations\":[{\"operator\":\"Exists\"}],\"containers\":[{\"name\":\"check\",\"image\":\"busybox:latest\",\"command\":[\"sh\",\"-c\",\"chroot /host df -h / | tail -1\"],\"securityContext\":{\"privileged\":true},\"volumeMounts\":[{\"name\":\"host\",\"mountPath\":\"/host\"}]}],\"volumes\":[{\"name\":\"host\",\"hostPath\":{\"path\":\"/\"}}]}}" \
        2>/dev/null || echo "unknown")

    echo "Current filesystem: ${CURRENT_SIZE_OUTPUT}"

    # Extract size in GB for comparison
    local CURRENT_GB
    CURRENT_GB=$(echo "${CURRENT_SIZE_OUTPUT}" | awk '{print $2}' | sed 's/G//' | cut -d. -f1 2>/dev/null || echo "0")

    # If already expanded (>100GB), skip
    if [[ "${CURRENT_GB}" =~ ^[0-9]+$ ]] && [[ ${CURRENT_GB} -gt 100 ]]; then
        echo "Filesystem already expanded to ${CURRENT_GB}GB. Skipping."
        return 0
    fi

    echo ""
    echo "Filesystem needs expansion. Running expansion steps..."
    echo ""

    # Delete any leftover pods from previous runs
    kubectl delete pod expand-gpu-disk --force --grace-period=0 2>/dev/null || true
    sleep 5

    # Create and run the expansion pod with detailed step-by-step verification
    cat <<'EXPAND_EOF' | sed "s/\${GPU_NODE}/${GPU_NODE}/g" | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: expand-gpu-disk
  namespace: default
spec:
  nodeName: ${GPU_NODE}
  hostPID: true
  tolerations:
  - operator: "Exists"
  priorityClassName: system-node-critical
  containers:
  - name: expand
    image: oraclelinux:8
    command: ["/bin/bash", "-c"]
    args:
    - |
      set -x  # Enable debug output
      echo "=========================================="
      echo "STEP 0: Initial disk state"
      echo "=========================================="
      chroot /host bash -c '
        echo "--- Partition table ---"
        fdisk -l /dev/sda 2>/dev/null | head -20
        echo ""
        echo "--- LVM Physical Volumes ---"
        pvs
        echo ""
        echo "--- LVM Volume Groups ---"
        vgs
        echo ""
        echo "--- LVM Logical Volumes ---"
        lvs
        echo ""
        echo "--- Current filesystem ---"
        df -h /
      '

      echo ""
      echo "=========================================="
      echo "STEP 1: Expand partition using growpart"
      echo "=========================================="
      echo "This is the CRITICAL step - partition must be expanded first!"
      chroot /host bash -c '
        # Install growpart if not available
        if ! command -v growpart &>/dev/null; then
          echo "Installing cloud-utils-growpart..."
          yum install -y cloud-utils-growpart 2>/dev/null || dnf install -y cloud-utils-growpart 2>/dev/null || true
        fi

        echo "Running growpart on /dev/sda partition 3..."
        growpart /dev/sda 3 2>&1 || echo "growpart returned non-zero (partition may already be expanded)"

        echo "Partition table after growpart:"
        fdisk -l /dev/sda 2>/dev/null | grep "^/dev/sda"
      '

      # Give kernel time to re-read partition table
      sleep 5

      echo ""
      echo "=========================================="
      echo "STEP 2: Resize LVM Physical Volume"
      echo "=========================================="
      chroot /host bash -c '
        echo "Running pvresize on /dev/sda3..."
        pvresize /dev/sda3
        echo ""
        echo "PV size after pvresize:"
        pvs /dev/sda3
      '

      echo ""
      echo "=========================================="
      echo "STEP 3: Extend LVM Logical Volume"
      echo "=========================================="
      chroot /host bash -c '
        echo "Running lvextend to use all free space..."
        lvextend -l +100%FREE /dev/ocivolume/root 2>&1 || echo "lvextend returned non-zero (may already be extended)"
        echo ""
        echo "LV size after lvextend:"
        lvs /dev/ocivolume/root
      '

      echo ""
      echo "=========================================="
      echo "STEP 4: Grow XFS filesystem"
      echo "=========================================="
      chroot /host bash -c '
        echo "Running xfs_growfs on root filesystem..."
        xfs_growfs /
        echo ""
        echo "Filesystem size after xfs_growfs:"
        df -h /
      '

      echo ""
      echo "=========================================="
      echo "EXPANSION COMPLETE"
      echo "=========================================="
      chroot /host df -h /
      echo "EXPANSION_DONE_MARKER"
    securityContext:
      privileged: true
    volumeMounts:
    - name: host
      mountPath: /host
  volumes:
  - name: host
    hostPath:
      path: /
  restartPolicy: Never
EXPAND_EOF

    # Wait for the pod to be created and start running
    echo "Waiting for expansion pod to start..."
    for i in {1..30}; do
        local POD_PHASE
        POD_PHASE=$(kubectl get pod expand-gpu-disk -o jsonpath='{.status.phase}' 2>/dev/null || echo "NotFound")
        if [[ "${POD_PHASE}" == "Running" ]] || [[ "${POD_PHASE}" == "Succeeded" ]] || [[ "${POD_PHASE}" == "Failed" ]]; then
            echo "Pod is ${POD_PHASE}"
            break
        fi
        echo "  Waiting for pod to start... (${i}/30)"
        sleep 5
    done

    # Stream logs while waiting for completion (max 5 minutes)
    echo ""
    echo "--- Expansion pod logs (streaming) ---"
    timeout 300 kubectl logs -f expand-gpu-disk 2>/dev/null || true
    echo "--- End of logs ---"
    echo ""

    # Check final pod status
    local FINAL_STATUS
    FINAL_STATUS=$(kubectl get pod expand-gpu-disk -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
    echo "Expansion pod final status: ${FINAL_STATUS}"

    # Check if expansion marker was output
    local LOGS
    LOGS=$(kubectl logs expand-gpu-disk 2>/dev/null || echo "")
    if echo "${LOGS}" | grep -q "EXPANSION_DONE_MARKER"; then
        echo "✓ Expansion script completed successfully"
    else
        echo "Warning: Expansion script may not have completed fully"
    fi

    # Cleanup expansion pod
    kubectl delete pod expand-gpu-disk --force --grace-period=0 2>/dev/null || true

    # Restart kubelet to refresh node status with new allocatable storage
    echo ""
    echo "Restarting kubelet to update node allocatable storage..."
    kubectl delete pod restart-kubelet --force --grace-period=0 2>/dev/null || true
    sleep 3

    cat <<RESTART_EOF | sed "s/\${GPU_NODE}/${GPU_NODE}/g" | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: restart-kubelet
  namespace: default
spec:
  nodeName: ${GPU_NODE}
  hostPID: true
  tolerations:
  - operator: "Exists"
  priorityClassName: system-node-critical
  containers:
  - name: restart
    image: busybox:latest
    command: ["/bin/sh", "-c"]
    args:
    - |
      echo "Restarting kubelet..."
      chroot /host systemctl restart kubelet
      echo "Kubelet restarted. Waiting for it to stabilize..."
      sleep 10
      echo "RESTART_DONE"
    securityContext:
      privileged: true
    volumeMounts:
    - name: host
      mountPath: /host
  volumes:
  - name: host
    hostPath:
      path: /
  restartPolicy: Never
RESTART_EOF

    # Wait for kubelet restart to complete
    echo "Waiting for kubelet restart..."
    for i in {1..24}; do
        local RESTART_STATUS
        RESTART_STATUS=$(kubectl get pod restart-kubelet -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
        if [[ "${RESTART_STATUS}" == "Succeeded" ]]; then
            echo "Kubelet restart completed"
            break
        elif [[ "${RESTART_STATUS}" == "Failed" ]]; then
            echo "Warning: Kubelet restart pod failed"
            break
        fi
        sleep 5
    done

    kubectl delete pod restart-kubelet --force --grace-period=0 2>/dev/null || true

    # Wait for node to be ready again after kubelet restart
    echo "Waiting for node to be ready..."
    kubectl wait --for=condition=Ready node "${GPU_NODE}" --timeout=120s 2>/dev/null || true

    # Additional wait for kubelet to update allocatable resources
    echo "Waiting for kubelet to report updated allocatable storage (60 seconds)..."
    sleep 60

    # Verify final filesystem size
    echo ""
    echo "=============================================="
    echo "VERIFICATION"
    echo "=============================================="
    local FINAL_SIZE_OUTPUT
    FINAL_SIZE_OUTPUT=$(kubectl run verify-disk-size --rm -i --restart=Never \
        --image=busybox:latest \
        --overrides="{\"spec\":{\"nodeName\":\"${GPU_NODE}\",\"tolerations\":[{\"operator\":\"Exists\"}],\"containers\":[{\"name\":\"check\",\"image\":\"busybox:latest\",\"command\":[\"sh\",\"-c\",\"chroot /host df -h / | tail -1\"],\"securityContext\":{\"privileged\":true},\"volumeMounts\":[{\"name\":\"host\",\"mountPath\":\"/host\"}]}],\"volumes\":[{\"name\":\"host\",\"hostPath\":{\"path\":\"/\"}}]}}" \
        2>/dev/null || echo "unknown")

    echo "Final filesystem: ${FINAL_SIZE_OUTPUT}"

    local FINAL_GB
    FINAL_GB=$(echo "${FINAL_SIZE_OUTPUT}" | awk '{print $2}' | sed 's/G//' | cut -d. -f1 2>/dev/null || echo "0")

    if [[ "${FINAL_GB}" =~ ^[0-9]+$ ]] && [[ ${FINAL_GB} -gt 100 ]]; then
        echo ""
        echo "✓ SUCCESS: Filesystem expanded to ${FINAL_GB}GB"
        echo ""
    else
        echo ""
        echo "⚠ WARNING: Filesystem may not have expanded properly (${FINAL_GB}GB)"
        echo ""
        echo "Manual intervention may be needed. You can run:"
        echo "  kubectl apply -f - <<EOF"
        echo "  apiVersion: v1"
        echo "  kind: Pod"
        echo "  ... (create privileged debug pod)"
        echo "  EOF"
        echo ""
        echo "Then inside the pod, run:"
        echo "  chroot /host bash"
        echo "  growpart /dev/sda 3"
        echo "  pvresize /dev/sda3"
        echo "  lvextend -l +100%FREE /dev/ocivolume/root"
        echo "  xfs_growfs /"
        echo "  df -h /"
        echo ""
    fi
}

# Fix router memory (default 500Mi causes OOMKill)
fix_router_memory() {
    echo "Increasing router memory to prevent OOMKill..."
    kubectl patch deployment vllm-deployment-router --type='json' -p='[
      {"op": "replace", "path": "/spec/template/spec/containers/0/resources/requests/memory", "value": "512Mi"},
      {"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits/memory", "value": "1Gi"}
    ]' 2>/dev/null || echo "Router deployment not found yet, will be patched after vLLM deployment"
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
    if helm status vllm &>/dev/null; then
        helm uninstall vllm
    else
        echo "No Helm release found to uninstall."
    fi

    # Delete PVCs
    echo "Deleting PVCs..."
    if kubectl get pvc -o name 2>/dev/null | grep -q .; then
        kubectl delete pvc --all
    else
        echo "No PVCs found to delete."
    fi

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
                if ! oci_cmd ce node-pool delete --node-pool-id "${POOL_ID}" --force; then
                    echo "Warning: Failed to delete node pool: ${POOL_ID}"
                fi
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
                    if ! oci_cmd network subnet delete --subnet-id "${SUBNET_ID}" --force; then
                        echo "    Warning: Failed to delete subnet: ${SUBNET_ID}"
                    fi
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
                if ! oci_cmd network route-table update --rt-id "${RT_ID}" --route-rules '[]' --force; then
                    echo "Warning: Failed to clear rules from route table: ${RT_ID}"
                fi
            fi
        done

        sleep 10

        # Delete Service Gateway
        echo "Deleting Service Gateway..."
        SGW_JSON=$(oci_cmd network service-gateway list \
            --compartment-id "${OCI_COMPARTMENT_ID}" \
            --vcn-id "${VCN_ID}" \
            --query "data[*].id" 2>/dev/null || echo "[]")

        echo "${SGW_JSON}" | jq -r '.[]?' 2>/dev/null | while read -r SGW_ID; do
            if [[ -n "${SGW_ID}" ]]; then
                echo "Deleting service gateway: ${SGW_ID}"
                if ! oci_cmd network service-gateway delete --service-gateway-id "${SGW_ID}" --force; then
                    echo "Warning: Failed to delete service gateway: ${SGW_ID}"
                fi
            fi
        done

        # Delete NAT Gateway
        echo "Deleting NAT Gateway..."
        NAT_JSON=$(oci_cmd network nat-gateway list \
            --compartment-id "${OCI_COMPARTMENT_ID}" \
            --vcn-id "${VCN_ID}" \
            --query "data[*].id" 2>/dev/null || echo "[]")

        echo "${NAT_JSON}" | jq -r '.[]?' 2>/dev/null | while read -r NAT_ID; do
            if [[ -n "${NAT_ID}" ]]; then
                echo "Deleting NAT gateway: ${NAT_ID}"
                if ! oci_cmd network nat-gateway delete --nat-gateway-id "${NAT_ID}" --force; then
                    echo "Warning: Failed to delete NAT gateway: ${NAT_ID}"
                fi
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
                if ! oci_cmd network internet-gateway delete --ig-id "${IGW_ID}" --force; then
                    echo "Warning: Failed to delete internet gateway: ${IGW_ID}"
                fi
            fi
        done

        sleep 30

        # Delete non-default route tables
        echo "Deleting route tables..."
        echo "${RT_JSON}" | jq -r '.[]?' 2>/dev/null | while read -r RT_ID; do
            if [[ -n "${RT_ID}" ]]; then
                echo "Deleting route table: ${RT_ID}"
                if ! oci_cmd network route-table delete --rt-id "${RT_ID}" --force; then
                    echo "Warning: Failed to delete route table: ${RT_ID}"
                fi
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
                if ! oci_cmd network security-list delete --security-list-id "${SL_ID}" --force; then
                    echo "Warning: Failed to delete security list: ${SL_ID}"
                fi
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
    add_cpu_nodepool  # Must be created before GPU nodes for kube-system workloads
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
        echo "  $0 deploy-vllm [HELM_VALUES_FILE]"
        echo ""
        echo "This will:"
        echo "  1. Install NVIDIA device plugin"
        echo "  2. Apply storage classes"
        echo "  3. Expand GPU disk to full boot volume size"
        echo "  4. Deploy vLLM stack"
        echo "  5. Fix router memory to prevent OOMKill"
        echo ""
        echo "Or run steps manually:"
        echo "  kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.1/nvidia-device-plugin.yml"
        echo "  kubectl apply -f ${SCRIPT_DIR}/oci-block-storage-sc.yaml"
        echo "  $0 expand-disk   # Expand GPU filesystem to full boot volume"
        echo "  helm repo add vllm https://vllm-project.github.io/production-stack && helm repo update"
        echo "  helm upgrade -i --wait vllm vllm/vllm-stack -f ${2:-${SCRIPT_DIR}/production_stack_specification.yaml}"
        echo "  $0 fix-router    # Increase router memory to prevent OOMKill"
        echo ""
    else
        install_nvidia_device_plugin
        apply_storage_class
        expand_gpu_disk
        deploy_vllm_stack "${2:-}"
        fix_router_memory
        echo ""
        echo "Setup complete! Your vLLM stack is ready."
        echo "Check pods with: kubectl get pods"
        echo "Get service endpoint: kubectl get svc"
    fi
    ;;
deploy-vllm)
    # For private clusters: complete deployment after SSH tunnel is established
    echo "Completing vLLM deployment (private cluster)..."
    install_nvidia_device_plugin
    apply_storage_class

    # Wait for GPU node to be ready
    echo "Waiting for GPU node to be ready..."
    kubectl wait --for=condition=Ready nodes -l app=gpu --timeout=600s || true

    expand_gpu_disk
    deploy_vllm_stack "${2:-}"

    # Wait a bit for router to be created
    echo "Waiting for router deployment..."
    sleep 30
    fix_router_memory

    echo ""
    echo "Deployment complete! Your vLLM stack is ready."
    echo "Check pods with: kubectl get pods"
    echo "Get service endpoint: kubectl get svc"
    ;;
expand-disk)
    # Expand GPU node filesystem to use full boot volume
    expand_gpu_disk
    ;;
fix-router)
    # Increase router memory to prevent OOMKill
    fix_router_memory
    ;;
cleanup)
    validate_env
    cleanup
    ;;
*)
    echo "Usage: $0 <command> [HELM_VALUES_FILE]"
    echo ""
    echo "Commands:"
    echo "  setup       - Create OKE cluster with GPU node pool (full deployment for public clusters)"
    echo "  deploy-vllm - Deploy vLLM stack (for private clusters, after SSH tunnel is active)"
    echo "  expand-disk - Expand GPU node filesystem to full boot volume size"
    echo "  fix-router  - Increase router memory to 1Gi (prevents OOMKill)"
    echo "  cleanup     - Delete all resources created by this script"
    echo ""
    echo "Environment variables:"
    echo "  OCI_PROFILE         - OCI CLI profile (default: DEFAULT)"
    echo "  OCI_COMPARTMENT_ID  - Required: OCI compartment OCID"
    echo "  OCI_REGION          - OCI region (default: us-ashburn-1)"
    echo "  CLUSTER_NAME        - Cluster name (default: production-stack)"
    echo "  GPU_SHAPE           - GPU shape (default: VM.GPU.A10.1)"
    echo "  GPU_BOOT_VOLUME_GB  - Boot volume size in GB (default: 200)"
    echo "  GPU_AD_INDEX        - Availability domain index (default: 1 for Ashburn AD-2)"
    echo "  PRIVATE_CLUSTER     - Use private endpoint + bastion (default: true)"
    echo "  BASTION_CLIENT_CIDR - Allowed CIDR for bastion access (default: 0.0.0.0/0)"
    echo "  GPU_NODE_COUNT      - Number of GPU nodes (default: 1)"
    echo ""
    echo "Typical usage for private cluster:"
    echo "  1. $0 setup                    # Creates cluster + bastion"
    echo "  2. Create bastion session and establish SSH tunnel"
    echo "  3. $0 deploy-vllm              # Deploys vLLM stack after tunnel is active"
    echo ""
    echo "IMPORTANT: GPU shape availability varies by region and AD:"
    echo "  - us-ashburn-1: VM.GPU.A10.1 available in AD-2 and AD-3 (use GPU_AD_INDEX=1 or 2)"
    echo "  - us-chicago-1: VM.GPU.A10.1 available in AD-1 only (use GPU_AD_INDEX=0)"
    exit 1
    ;;
esac
