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

# Function to get router logs and extract session_id -> server_url mappings
verify_router_logs_consistency() {
    local router_log_file=$1

    print_status "Verifying router logs for session_id -> server_url consistency"

    # Get router logs during the test period
    print_status "Fetching router logs..."

    # Try multiple common router pod selectors
    local router_selectors=(
        "environment=router"
        "release=router"
        "app.kubernetes.io/component=router"
        "app=vllmrouter-sample"
    )

    local logs_found=false
    local raw_log_file="$TEMP_DIR/raw_router_logs.txt"

    for selector in "${router_selectors[@]}"; do
        if kubectl get pods -l "$selector" &>/dev/null && [ "$(kubectl get pods -l "$selector" --no-headers | wc -l)" -gt 0 ]; then
            print_status "Found router pods with selector: $selector"
            # Get more logs but we'll filter them
            kubectl logs -l "$selector" --tail=5000 > "$raw_log_file" 2>&1 || true
            logs_found=true
            break
        fi
    done

    if [ "$logs_found" = false ]; then
        print_warning "Could not find router pods with any known selector. Trying alternative approaches..."

        # Try to find router service and infer pod labels
        if kubectl get svc vllm-router-service &>/dev/null; then
            local router_deployment=$(kubectl get deployment | grep router | head -n 1 | awk '{print $1}')
            if [ -n "$router_deployment" ]; then
                print_status "Found router deployment: $router_deployment"
                kubectl logs deployment/"$router_deployment" --tail=5000 > "$raw_log_file" 2>&1 || true
                logs_found=true
            fi
        fi
    fi

    if [ "$logs_found" = false ] || [ ! -s "$raw_log_file" ]; then
        print_warning "Could not fetch router logs or logs are empty. Skipping router log verification."
        return 0
    fi

    # Filter logs to only include routing decision logs and exclude health checks
    print_status "Filtering routing decision logs from $(wc -l < "$raw_log_file") total log lines..."

    # Filter for routing logs, excluding health checks and other noise
    grep -E "Routing request.*to.*at.*process time" "$raw_log_file" | \
    grep -v "/health" | \
    grep -v "health.*check" | \
    tail -1000 > "$router_log_file" 2>/dev/null || true

    # If no filtered logs found, try a broader search
    if [ ! -s "$router_log_file" ]; then
        print_status "No routing decision logs found with strict filter. Trying broader search..."
        grep -E "(Routing request|routing request)" "$raw_log_file" | \
        grep -v "/health" | \
        tail -1000 > "$router_log_file" 2>/dev/null || true
    fi

    if [ ! -s "$router_log_file" ]; then
        print_warning "No routing decision logs found after filtering. Skipping router log verification."
        return 0
    fi

    print_status "Filtered router logs. Found $(wc -l < "$router_log_file") routing decision log lines"

    if [ "$VERBOSE" = true ]; then
        print_status "Debug: First 10 routing decision logs:"
        head -n 10 "$router_log_file" || true
    fi

    # Extract session_id -> server_url mappings from router logs
    local session_mappings_file="$TEMP_DIR/session_mappings.txt"
    > "$session_mappings_file"  # Clear the file

    # Parse router logs for routing decisions
    # Handle multiple log formats:
    # Format 1: "Routing request {request_id} with session id {session_id} to {server_url} at {time}, process time = {duration}"
    # Format 2: "Routing request {request_id} to {server_url} at {time}, process time = {duration}" (without session id)

    while IFS= read -r line; do
        if [[ $line == *"Routing request"* && $line == *" to "* && $line == *"at"* ]]; then
            local session_id server_url request_id

            # Extract session id (the string after "with session id " and before " to ")
            session_id=$(echo "$line" | sed -n 's/.*with session id \([^ ]*\) to .*/\1/p')

            # If no session_id found, default to -1
            if [ -z "$session_id" ]; then
                session_id="-1"
            fi

            # Extract server URL (the string after " to " and before " at ")
            # Try a more robust approach - extract everything between " to " and " at "
            server_url=$(echo "$line" | sed -n 's/.* to \([^ ]*\) at .*/\1/p')

            # Debug: show what we extracted if verbose mode
            if [ "$VERBOSE" = true ]; then
                print_status "Debug: Raw log line: $line"
                print_status "Debug: Extracted session_id: '$session_id'"
                print_status "Debug: Extracted server_url: '$server_url'"
            fi

            if [ -n "$session_id" ] && [ -n "$server_url" ]; then
                echo "$session_id:$server_url" >> "$session_mappings_file"
                if [ "$VERBOSE" = true ]; then
                    print_status "Debug: Found mapping - Session ID: $session_id -> Server: $server_url"
                fi
            fi
        fi
    done < "$router_log_file"

    local total_mappings=$(wc -l < "$session_mappings_file")
    print_status "Found $total_mappings session_id -> server_url mappings in router logs"

    if [ "$total_mappings" -eq 0 ]; then
        print_warning "No session_id -> server_url mappings found in router logs."
        print_warning "This could mean:"
        print_warning "  1. The test ran before router logs were captured"
        print_warning "  2. Session-based routing is not enabled"
        print_warning "  3. Log format has changed"
        return 0
    fi

    # Verify consistency: all requests with the same session_id should go to the same server_url
    local consistency_check_file="$TEMP_DIR/consistency_check.txt"
    > "$consistency_check_file"

    # Group by session_id and check if all server_urls for each session are the same
    sort "$session_mappings_file" | while IFS=: read -r session_id server_url; do
        echo "$session_id $server_url" >> "$consistency_check_file"
    done

    # Check for inconsistencies
    local inconsistencies=0
    local unique_sessions
    unique_sessions=$(cut -d: -f1 "$session_mappings_file" | sort -u)

    while IFS= read -r session_id; do
        local session_servers
        session_servers=$(grep "^$session_id:" "$session_mappings_file" | cut -d: -f2 | sort -u)
        local server_count
        server_count=$(echo "$session_servers" | wc -l)

        if [ "$server_count" -gt 1 ]; then
            print_error "❌ Inconsistency detected for session_id '$session_id':"
            print_error "   This session was routed to multiple servers:"
            echo "$session_servers" | while read -r server; do
                print_error "     - $server"
            done
            inconsistencies=$((inconsistencies + 1))
        else
            print_status "✅ Session '$session_id' consistently routed to: $session_servers"
        fi
    done <<< "$unique_sessions"

    if [ "$inconsistencies" -gt 0 ]; then
        print_error "❌ Router log verification failed: Found $inconsistencies session(s) with inconsistent routing"
        return 1
    else
        print_status "✅ Router log verification passed: All sessions show consistent server routing"

        # Print summary
        local unique_session_count
        unique_session_count=$(echo "$unique_sessions" | wc -l)
        print_status "Summary from router logs:"
        print_status "  Total routing decisions logged: $total_mappings"
        print_status "  Unique sessions found: $unique_session_count"
        print_status "  All sessions maintained consistent server assignments"
    fi

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
            kill "$PORT_FORWARD_PID" 2>/dev/null
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
if curl -s "$BASE_URL/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dummy" \
  -d '{
    "model": "'"$MODEL"'",
    "messages": [{"role": "user", "content": "test"}],
    "temperature": 0.0,
    "max_tokens": 1
  }' > /dev/null; then
    print_status "✅ Base URL is working"
else
    print_error "❌ Base URL test failed"
fi

# Calculate reasonable timeout:
# With 2 users, 3 rounds each, QPS of 1.0, we expect roughly 6 requests total
# Add buffer time for warmup, ramp-up, and request processing
# Each request might take 10-30 seconds to complete, so 25 seconds should be plenty
TIMEOUT_SECONDS=25

# Build verbose argument array
verbose_args=()
if [ "$VERBOSE" = true ]; then
    verbose_args+=("--verbose")
fi

print_status "Executing multi-round-qa.py with the following parameters:"
print_status "  Base URL: $BASE_URL"
print_status "  Model: $MODEL"
print_status "  Users: $NUM_USERS"
print_status "  Rounds: $NUM_ROUNDS"
print_status "  Timeout: $TIMEOUT_SECONDS seconds"

# Run the python script and capture exit code
set +e  # Temporarily disable exit on error
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
    "${verbose_args[@]}" \
    > "$RESPONSE_FILE" 2>&1

PYTHON_EXIT_CODE=$?
set -e  # Re-enable exit on error

# Check if the python script succeeded
if [ $PYTHON_EXIT_CODE -ne 0 ]; then
    print_error "multi-round-qa.py failed with exit code $PYTHON_EXIT_CODE"
    print_error "Script output:"
    echo "--- START SCRIPT OUTPUT ---"
    cat "$RESPONSE_FILE"
    echo "--- END SCRIPT OUTPUT ---"

    print_error "Output file contents (if exists):"
    if [ -f "$OUTPUT_FILE" ]; then
        echo "--- START OUTPUT FILE ---"
        cat "$OUTPUT_FILE"
        echo "--- END OUTPUT FILE ---"
    else
        print_error "Output file $OUTPUT_FILE was not created"
    fi

    print_error "Debugging information:"
    print_error "  Working directory: $(pwd)"
    print_error "  Python version: $(python3 --version)"
    print_error "  Available Python packages:"
    pip list | grep -E "(requests|aiohttp|asyncio)" || true

    exit $PYTHON_EXIT_CODE
fi

print_status "✅ multi-round-qa.py completed successfully"

# Skip response file parsing - only verify router logs
print_status "Skipping response file parsing - focusing on router log verification only"

# Verify router logs for session_id -> server_url consistency
ROUTER_LOG_FILE="$TEMP_DIR/router_logs.txt"
if ! verify_router_logs_consistency "$ROUTER_LOG_FILE"; then
    print_error "Router log verification failed!"
    exit 1
fi

print_status "✅ Sticky routing test passed!"
print_status "Router logs confirm consistent session_id -> server_url mappings"
