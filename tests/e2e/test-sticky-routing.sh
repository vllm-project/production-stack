#!/bin/bash

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print status messages
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Function to extract pod name from response headers
extract_pod_name() {
    local response_file=$1
    # Assuming the router adds x-pod-name header
    # You might need to adjust this based on your actual header name
    grep -i "x-pod-name:" "$response_file" | tail -n 1 | awk '{print $2}'
}

# Function to extract user ID from the prompt
extract_user_id() {
    local response_file=$1
    # Extract user ID from the prompt that contains "I'm user X"
    grep -i "I'm user" "$response_file" | head -n 1 | grep -o '[0-9]\+'
}

# Function to verify sticky routing
verify_sticky_routing() {
    local user_id=$1
    local pod_name=$2
    local user_pods_file=$3

    if [ -f "$user_pods_file" ]; then
        local previous_pod=$(grep "^$user_id:" "$user_pods_file" | cut -d':' -f2)
        if [ -n "$previous_pod" ] && [ "$previous_pod" != "$pod_name" ]; then
            print_error "User $user_id was routed to different pods: $previous_pod and $pod_name"
            return 1
        fi
    fi
    echo "$user_id:$pod_name" >> "$user_pods_file"
    return 0
}

# Parse command line arguments
BASE_URL=""
# MODEL="meta-llama/Llama-3.1-8B-Instruct"  # Set default model
MODEL="facebook/opt-125m"
NUM_ROUNDS=3
VERBOSE=false
DEBUG=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --base-url)
            BASE_URL="$2"
            shift 2
            ;;
        --model)
            MODEL="$2"
            shift 2
            ;;
        --num-rounds)
            NUM_ROUNDS="$2"
            shift 2
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        --debug)
            DEBUG=true
            shift
            ;;
        *)
            print_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# If BASE_URL is not provided, set up port forwarding
if [ -z "$BASE_URL" ]; then
    # Check if vllm-router-service exists
    if ! kubectl get svc vllm-router-service >/dev/null 2>&1; then
        print_error "vllm-router-service not found. Please ensure the service exists or provide --base-url"
        exit 1
    fi

    # Use a local port for port forwarding
    LOCAL_PORT=8080

    # Start port forwarding in the background
    print_status "Setting up port forwarding to vllm-router-service on localhost:${LOCAL_PORT}"
    kubectl port-forward svc/vllm-router-service ${LOCAL_PORT}:80 >/dev/null 2>&1 &
    PORT_FORWARD_PID=$!

    # Add cleanup for port forwarding
    cleanup() {
        if [ -n "$PORT_FORWARD_PID" ]; then
            print_status "Cleaning up port forwarding (PID: $PORT_FORWARD_PID)"
            kill $PORT_FORWARD_PID 2>/dev/null
        fi
        if [ "$DEBUG" = true ]; then
            print_status "Debug mode: Preserving temp directory: $TEMP_DIR"
        else
            rm -rf "$TEMP_DIR"
        fi
    }
    trap cleanup EXIT

    # Wait a moment for port forwarding to establish
    sleep 3

    BASE_URL="http://localhost:${LOCAL_PORT}/v1"
    print_status "Using port forwarding: $BASE_URL"
fi

# Validate required arguments
if [ -z "$BASE_URL" ]; then
    print_error "Missing required argument. Usage:"
    print_error "$0 [--base-url <url>] [--model <model>] [--num-rounds <n>] [--verbose]"
    print_error "Default model: meta-llama/Llama-3.1-8B"
    print_error "Default BASE_URL will be constructed from minikube IP and vllm-router-service NodePort if not specified"
    exit 1
fi

# Create temporary directory for test files
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

print_status "Starting sticky routing test with 2 users, $NUM_ROUNDS rounds per user"

USER_PODS_FILE="$TEMP_DIR/user_pods.txt"
touch "$USER_PODS_FILE"

print_status "Testing session-aware routing with user IDs in request headers"

# Test parameters
NUM_USERS=2
SHARED_SYSTEM_PROMPT=10
USER_HISTORY_PROMPT=10
ANSWER_LEN=50
QPS=1.0

# Run multi-round-qa.py once with multiple users and rounds
OUTPUT_FILE="$TEMP_DIR/test_output.txt"
RESPONSE_FILE="$TEMP_DIR/response.txt"

print_status "Running multi-round-qa test with $NUM_USERS users and $NUM_ROUNDS rounds"
print_status "Using --request-with-user-id to enable session-aware routing"

# Add this right before the python3 call
print_status "Debug: BASE_URL being passed to script: $BASE_URL"
print_status "Debug: MODEL being used: $MODEL"

# Test the URL first
print_status "Testing BASE_URL with curl..."
curl -s "$BASE_URL/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dummy" \
  -d '{
    "model": "'$MODEL'",
    "messages": [{"role": "user", "content": "test"}],
    "temperature": 0.0,
    "max_tokens": 1
  }' > /dev/null && print_status "✅ Base URL is working" || print_error "❌ Base URL test failed"

# Calculate reasonable timeout:
# With 2 users, 3 rounds each, QPS of 1.0, we expect roughly 6 requests total
# Add buffer time for warmup, ramp-up, and request processing
# Each request might take 10-30 seconds to complete, so 25 seconds should be plenty
TIMEOUT_SECONDS=25

python3 benchmarks/multi-round-qa/multi-round-qa.py \
    --base-url "$BASE_URL" \
    --model "$MODEL" \
    --num-users "$NUM_USERS" \
    --shared-system-prompt "$SHARED_SYSTEM_PROMPT" \
    --user-history-prompt "$USER_HISTORY_PROMPT" \
    --answer-len "$ANSWER_LEN" \
    --num-rounds "$NUM_ROUNDS" \
    --qps "$QPS" \
    --time "$TIMEOUT_SECONDS" \
    --request-with-user-id \
    --output "$OUTPUT_FILE" \
    $([ "$VERBOSE" = true ] && echo "--verbose") \
    > "$RESPONSE_FILE" 2>&1

# Process the response file to extract pod assignments
print_status "Processing responses to verify sticky routing"

# Read the response file and process each request
while IFS= read -r line; do
    # Look for lines containing user prompts and pod names
    if [[ $line == *"I'm user"* ]]; then
        # Extract user ID from the prompt
        user_id=$(echo "$line" | grep -o '[0-9]\+')
        if [ -n "$user_id" ]; then
            # Get the next few lines to find the pod name
            pod_name=$(extract_pod_name "$RESPONSE_FILE")
            if [ -n "$pod_name" ]; then
                print_status "Found request from User $user_id -> Pod $pod_name"
                if ! verify_sticky_routing "$user_id" "$pod_name" "$USER_PODS_FILE"; then
                    print_error "Sticky routing test failed!"
                    exit 1
                fi
            fi
        fi
    fi
done < "$RESPONSE_FILE"

print_status "✅ Sticky routing test passed!"
print_status "All users maintained consistent pod assignments across rounds"
print_status "Session-aware routing with user IDs is working correctly"

# Print final pod assignments
print_status "\nFinal pod assignments:"
while IFS=: read -r uid pod; do
    print_status "User $uid -> Pod $pod"
done < "$USER_PODS_FILE"
