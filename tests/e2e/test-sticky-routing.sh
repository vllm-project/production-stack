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
            local router_deployment
            router_deployment=$(kubectl get deployment | grep router | head -n 1 | awk '{print $1}')
            if [ -n "$router_deployment" ]; then
                print_status "Found router deployment: $router_deployment"
                kubectl logs deployment/"$router_deployment" --tail=5000 > "$raw_log_file" 2>&1 || true
                logs_found=true
            fi
        fi
    fi

    if [ "$logs_found" = false ] || [ ! -s "$raw_log_file" ]; then
        print_error "Could not fetch router logs or logs are empty. Router log verification failed."
        return 1
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
        print_error "No routing decision logs found after filtering. Router log verification failed."
        return 1
    fi

    print_status "Filtered router logs. Found $(wc -l < "$router_log_file") routing decision log lines"

    if [ "$VERBOSE" = true ]; then
        print_status "Debug: First 10 routing decision logs:"
        head -n 10 "$router_log_file" || true
    fi

    # Extract session_id -> server_url mappings from router logs
    local session_mappings_file="$TEMP_DIR/session_mappings.txt"
    true > "$session_mappings_file"  # Clear the file

    # Parse router logs for routing decisions
    # Handle multiple log formats:
    # Format 1: "Routing request {request_id} with session id {session_id} to {server_url} at {time}, process time = {duration}"
    # Format 2: "Routing request {request_id} to {server_url} at {time}, process time = {duration}" (without session id)

    while IFS= read -r line; do
        if [[ $line == *"Routing request"* && $line == *" to "* && $line == *"at"* ]]; then
            local session_id server_url

            # Extract session id (the string after "with session id " and before " to ")
            session_id=$(echo "$line" | sed -n 's/.*with session id \([^ ]*\) to .*/\1/p')

            # Handle missing session_id - set default for non-session requests
            if [ -z "$session_id" ]; then
                session_id=-1
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
                # Only record session-aware routing (skip session_id -1)
                if [ "$session_id" != "-1" ] && [ "$session_id" != "None" ]; then
                    echo "$session_id|$server_url" >> "$session_mappings_file"
                    if [ "$VERBOSE" = true ]; then
                        print_status "Debug: Found session-aware mapping - Session ID: $session_id -> Server: $server_url"
                    fi
                elif [ "$VERBOSE" = true ]; then
                    print_status "Debug: Skipping non-session request - Session ID: $session_id -> Server: $server_url"
                fi
            fi
        fi
    done < "$router_log_file"

    local total_mappings
    total_mappings=$(wc -l < "$session_mappings_file")
    print_status "Found $total_mappings session-aware routing mappings in router logs (excluding non-session requests)"

    if [ "$total_mappings" -eq 0 ]; then
        print_error "No session-aware routing mappings found in router logs."
        print_error "This could mean:"
        print_error "  1. The test ran before router logs were captured"
        print_error "  2. Session-based routing is not enabled"
        print_error "  3. All requests were non-session requests (session_id -1 or None)"
        print_error "  4. Log format has changed"
        print_error "Router log verification failed."
        return 1
    fi

    # Verify consistency: all requests with the same session_id should go to the same server_url
    local consistency_check_file="$TEMP_DIR/consistency_check.txt"
    true > "$consistency_check_file"

    # Group by session_id and check if all server_urls for each session are the same
    sort "$session_mappings_file" | while IFS=\| read -r session_id server_url; do
        echo "$session_id $server_url" >> "$consistency_check_file"
    done

    # Check for inconsistencies
    local inconsistencies=0
    local unique_sessions
    unique_sessions=$(cut -d\| -f1 "$session_mappings_file" | sort -u)

    while IFS= read -r session_id; do
        local session_servers
        session_servers=$(grep "^$session_id|" "$session_mappings_file" | cut -d\| -f2 | sort -u)
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
        print_status "  Total session-aware routing decisions: $total_mappings"
        print_status "  Unique sessions found: $unique_session_count"
        print_status "  All sessions maintained consistent server assignments"
        print_status "  (Non-session requests with session_id -1 or None were excluded from analysis)"
    fi

    return 0
}

# Parse command line arguments
BASE_URL=""
MODEL="meta-llama/Llama-3.1-8B-Instruct"  # Set default model
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

# Create temporary directory for test files
TEMP_DIR=$(mktemp -d)

# Also create a persistent results directory for CI artifacts
RESULTS_DIR="/tmp/sticky-routing-results-$(date +%s)"
mkdir -p "$RESULTS_DIR"

# Initialize PORT_FORWARD_PID to empty so cleanup can always reference it
PORT_FORWARD_PID=""

cleanup() {
    if [ -n "$PORT_FORWARD_PID" ]; then
        print_status "Cleaning up port forwarding (PID: $PORT_FORWARD_PID)"
        kill "$PORT_FORWARD_PID" 2>/dev/null
    fi
    if [ "${DEBUG:-false}" = true ]; then
        print_status "Debug mode: Preserving temp directory: $TEMP_DIR"
        print_status "Debug mode: Results also saved to: $RESULTS_DIR"
        # Copy temp files to results directory for CI
        cp -r "$TEMP_DIR"/* "$RESULTS_DIR"/ 2>/dev/null || true
    else
        rm -rf "$TEMP_DIR"
        # Still preserve some key files for CI even in non-debug mode
        cp "$TEMP_DIR"/router_logs.txt "$RESULTS_DIR"/ 2>/dev/null || true
        cp "$TEMP_DIR"/session_mappings.txt "$RESULTS_DIR"/ 2>/dev/null || true
        rm -rf "$TEMP_DIR"
    fi
}
trap cleanup EXIT

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

print_status "Starting sticky routing test with 2 users, $NUM_ROUNDS rounds per user"

print_status "Testing session-aware routing with user IDs in request headers"

# Test parameters
NUM_USERS=2

print_status "Running custom request test with $NUM_USERS users and $NUM_ROUNDS rounds"
print_status "Using x-user-id header to enable session-aware routing"

# Test the URL first
print_status "Testing BASE_URL with curl..."
if curl -s "$BASE_URL/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dummy" \
  -d '{
    "model": "'"$MODEL"'",
    "prompt": "test",
    "temperature": 0.0,
    "max_tokens": 1
  }' > /dev/null; then
    print_status "✅ Base URL is working"
else
    print_error "❌ Base URL test failed"
fi

# Custom script to send n x m requests with session headers
print_status "Executing custom request script with the following parameters:"
print_status "  Base URL: $BASE_URL"
print_status "  Model: $MODEL"
print_status "  Users: $NUM_USERS"
print_status "  Rounds: $NUM_ROUNDS"

# Function to send requests for a single user (runs in background)
send_user_requests() {
    local user=$1
    local session_id=$2
    local user_log_file="$TEMP_DIR/user_${user}_log.txt"
    local user_error_file="$TEMP_DIR/user_${user}_error.txt"

    exec > "$user_log_file" 2>"$user_error_file"

    echo "[User $user] Starting requests with session_id: $session_id"

    # For each round per user
    for round in $(seq 1 "$NUM_ROUNDS"); do
        echo "[User $user] Sending round $round/$NUM_ROUNDS (session_id: $session_id)"

        # Send the request with x-user-id header
        local response_file="$TEMP_DIR/response_${session_id}_${round}.json"

        curl -s "$BASE_URL/completions" \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer dummy" \
            -H "x-user-id: $session_id" \
            -d '{
                "model": "'"$MODEL"'",
                "prompt": "Hello, this is round '"$round"' from user '"$user"' with session '"$session_id"'. Please respond briefly.",
                "temperature": 0.7,
                "max_tokens": 50
            }' \
            -o "$response_file" \
            --max-time 30

        local curl_exit_code=$?
        if [ $curl_exit_code -ne 0 ]; then
            echo "[User $user] ERROR: Request failed for Round $round (session_id: $session_id) with curl exit code: $curl_exit_code"
            exit 1
        fi

        # Verify response is valid JSON and contains expected content
        if ! jq empty "$response_file" 2>/dev/null; then
            echo "[User $user] ERROR: Invalid JSON response for Round $round (session_id: $session_id)"
            echo "[User $user] Response content:"
            cat "$response_file"
            exit 1
        fi

        echo "[User $user] ✅ Response received for round $round (session_id: $session_id)"

        # Small delay between requests from same user to avoid overwhelming
        sleep 0.5
    done

    echo "[User $user] ✅ All $NUM_ROUNDS requests completed successfully"
    exit 0
}

# Function to send requests with session headers (parallel execution)
send_custom_requests() {
    local total_requests=$((NUM_USERS * NUM_ROUNDS))
    local pids=()

    print_status "Sending $total_requests total requests ($NUM_USERS users × $NUM_ROUNDS rounds) in parallel"

    # Start background processes for each user
    local session_id=1
    for user in $(seq 1 "$NUM_USERS"); do
        print_status "Starting background process for User $user (session_id: $session_id)"

        # Start user requests in background
        send_user_requests "$user" "$session_id" &
        local pid=$!
        pids+=("$pid")

        print_status "  User $user process started with PID: $pid"

        # Move to next session_id for next user
        session_id=$((session_id + 1))
    done

    print_status "All $NUM_USERS user processes started. Waiting for completion..."

    # Wait for all background processes and collect exit codes
    local failed_users=()
    local user=1
    for pid in "${pids[@]}"; do
        if wait "$pid"; then
            print_status "✅ User $user completed successfully"
        else
            local exit_code=$?
            print_error "❌ User $user failed with exit code: $exit_code"
            failed_users+=("$user")
        fi
        user=$((user + 1))
    done

    # Display logs from all users
    if [ "$VERBOSE" = true ]; then
        print_status "User process logs:"
        for user in $(seq 1 "$NUM_USERS"); do
            local user_log_file="$TEMP_DIR/user_${user}_log.txt"
            if [ -f "$user_log_file" ]; then
                echo "--- User $user Log ---"
                cat "$user_log_file"
                echo ""
            fi
        done
    fi

    # Check if any users failed
    if [ ${#failed_users[@]} -gt 0 ]; then
        print_error "Failed users: ${failed_users[*]}"

        # Show error logs for failed users
        for user in "${failed_users[@]}"; do
            local user_error_file="$TEMP_DIR/user_${user}_error.txt"
            if [ -f "$user_error_file" ] && [ -s "$user_error_file" ]; then
                print_error "Error log for User $user:"
                cat "$user_error_file"
            fi
        done

        return 1
    fi

    print_status "✅ All $total_requests requests completed successfully across $NUM_USERS parallel users"
    return 0
}

# Run the custom request script and capture exit code
set +e  # Temporarily disable exit on error
send_custom_requests
SCRIPT_EXIT_CODE=$?
set -e  # Re-enable exit on error

# Check if the custom script succeeded
if [ $SCRIPT_EXIT_CODE -ne 0 ]; then
    print_error "Custom request script failed with exit code $SCRIPT_EXIT_CODE"
    exit $SCRIPT_EXIT_CODE
fi

print_status "✅ Custom request script completed successfully"

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
