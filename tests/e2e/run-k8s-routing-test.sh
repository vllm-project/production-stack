#!/bin/bash

# Script to run k8s routing tests with different routing logic
# Based on test-routing.py structure
# Usage: ./run-k8s-routing-test.sh <test_type> [options]

set -euo pipefail

# Default values
TEST_TYPE=""
HELM_VALUES_FILE=""
MODEL="facebook/opt-125m"
NUM_REQUESTS=20
CHUNK_SIZE=128
VERBOSE=""
TIMEOUT_MINUTES=10
ROUTER_URL=""
LOG_FILE_PATH=""
RESULT_DIR="tests/e2e/k8s-discovery-results"
DISCOVERY_TYPE="k8s"
SESSION_KEY="x-user-id"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Function to show usage
show_usage() {
    cat << EOF
Usage: $0 <test_type> [options]

Test Type Options:
    roundrobin         - Test round-robin routing
    prefixaware        - Test prefix-aware routing
    kvaware           - Test KV-aware routing
    disaggregated-prefill - Test disaggregated prefill routing
    session           - Test session routing
    all               - Run all available tests sequentially

Options:
    -m, --model MODEL           Model to use (default: facebook/opt-125m)
    -r, --num-requests N        Number of requests to test (default: 20)
    -c, --chunk-size N          Chunk size for prefix-aware routing (default: 128)
    -u, --router-url URL        Router URL (default: auto-detect via port-forward)
    -l, --log-file-path PATH    Path to router log file (default: auto-fetch from k8s)
    -d, --result-dir DIR        Result directory (default: tests/e2e/static-discovery-results)
    -t, --discovery-type TYPE   Discovery type: static or k8s (default: k8s)
    -v, --verbose               Enable verbose output
    -t, --timeout N             Timeout in minutes (default: 10)
    --session-key KEY           Session key for session routing (default: x-user-id)
    -h, --help                  Show this help message

Examples:
    $0 roundrobin --model "facebook/opt-125m" --num-requests 30 --verbose
    $0 prefixaware --model "facebook/opt-125m" --chunk-size 256 --debug
    $0 session --model "facebook/opt-125m" --num-requests 30 --verbose
    $0 all --verbose --discovery-type k8s
    $0 roundrobin --router-url "http://localhost:30080" --discovery-type static

EOF
}

# Function to deploy helm chart
deploy_helm_chart() {
    local values_file=$1
    print_status "🚀 Deploying setup with helm using $values_file"
    if helm list -q | grep -q "^vllm$"; then
        print_status "📦 Upgrading existing vllm deployment"
        helm upgrade vllm ./helm -f "$values_file"
    else
        print_status "🚀 Installing new vllm deployment"
        helm install vllm ./helm -f "$values_file"
    fi
}

# Function to wait for pods
wait_for_pods() {
    print_status "⏳ Waiting for pods to be ready"
    chmod +x tests/e2e/wait-for-pods.sh
    tests/e2e/wait-for-pods.sh --pod-prefix vllm --timeout 300 --verbose
}

# Function to setup port forwarding
setup_port_forwarding() {
    print_status "Cleaning up port forwarding"
    pkill -f "kubectl port-forward" 2>/dev/null || true

    # Check if vllm-router-service exists
    if ! kubectl get svc vllm-router-service >/dev/null 2>&1; then
        print_error "vllm-router-service not found. Please ensure the service exists or provide --router-url"
        return 1
    fi

    local local_port=30080
    print_status "Setting up port forwarding to vllm-router-service on localhost:$local_port"

    # Start port forwarding in background
    kubectl port-forward svc/vllm-router-service ${local_port}:80 &
    local port_forward_pid=$!

    # Wait for port forwarding to establish
    sleep 3

    # Check if port forwarding is working
    if ! curl -s "http://localhost:$local_port/health" >/dev/null 2>&1; then
        print_error "Port forwarding failed. Router health check failed."
        kill $port_forward_pid 2>/dev/null || true
        return 1
    fi

    ROUTER_URL="http://localhost:$local_port"
    print_status "Port forwarding established: $ROUTER_URL"
    return 0
}

# Function to run test
run_test() {
    local test_type=$1
    local routing_logic=$2

    print_status "🧪 Running $test_type test with $routing_logic routing"

    # Build test command
    local test_cmd="python tests/e2e/test-routing.py"
    test_cmd="$test_cmd --discovery-type $DISCOVERY_TYPE"
    test_cmd="$test_cmd --routing-logic $routing_logic"
    test_cmd="$test_cmd --model \"$MODEL\""
    test_cmd="$test_cmd --num-requests $NUM_REQUESTS"
    test_cmd="$test_cmd --prefix-chunk-size $CHUNK_SIZE"
    test_cmd="$test_cmd --result-dir $RESULT_DIR"

    # Add router URL if provided
    if [ -n "$ROUTER_URL" ]; then
        test_cmd="$test_cmd --router-url \"$ROUTER_URL\""
    fi

    # Add log file path if provided
    if [ -n "$LOG_FILE_PATH" ]; then
        test_cmd="$test_cmd --log-file-path \"$LOG_FILE_PATH\""
    fi

    # Add verbose flag
    if [ "$VERBOSE" = "true" ]; then
        test_cmd="$test_cmd --verbose"
    fi

    if [ "$test_type" = "session" ]; then
        test_cmd="$test_cmd --session-key \"$SESSION_KEY\""
    fi

    print_status "Executing: $test_cmd"
    timeout "${TIMEOUT_MINUTES}m" bash -c "$test_cmd"
}

# Function to collect debug logs
collect_debug_logs() {
    local test_type=$1
    print_status "📋 Collecting logs for debugging"
    mkdir -p "$RESULT_DIR/debug-logs/test-type-$test_type"

    # Get router logs with multiple selectors
    local router_selectors=(
        "environment=router"
        "release=router"
        "app.kubernetes.io/component=router"
        "app=vllmrouter-sample"
    )

    for selector in "${router_selectors[@]}"; do
        if kubectl get pods -l "$selector" >/dev/null 2>&1; then
            print_status "Found router pods with selector: $selector"
            kubectl logs -l "$selector" --tail=100 > "$RESULT_DIR/debug-logs/test-type-$test_type/router-${selector//\//-}.log" 2>/dev/null || true
            break
        fi
    done

    # Get serving engine logs
    kubectl logs -l app.kubernetes.io/component=serving-engine --tail=100 > "$RESULT_DIR/debug-logs/test-type-$test_type/serving-engines.log" 2>/dev/null || true

    # Get pod status
    kubectl get pods -o wide > "$RESULT_DIR/debug-logs/test-type-$test_type/pod-status.txt" 2>/dev/null || true

    # Get services
    kubectl get svc > "$RESULT_DIR/debug-logs/test-type-$test_type/services.txt" 2>/dev/null || true

    # Get events
    kubectl get events --sort-by='.lastTimestamp' > "$RESULT_DIR/debug-logs/test-type-$test_type/events.txt" 2>/dev/null || true
}

# Function to cleanup resources
cleanup_resources() {
    print_status "🧹 Cleaning up resources"

    # Kill any port forwarding processes
    pkill -f "kubectl port-forward" 2>/dev/null || true

    # Uninstall helm chart
    helm uninstall vllm 2>/dev/null || true

    # Clean up docker images
    sudo docker image prune -f 2>/dev/null || true
}

# Function to run complete test
run_complete_test() {
    local test_type=$1
    local helm_values_file=$2
    local routing_logic=$3

    print_status "=========================================="
    print_status "Starting $test_type test"
    print_status "=========================================="

    # Deploy helm chart
    deploy_helm_chart "$helm_values_file"

    # Wait for pods
    wait_for_pods

    # Setup port forwarding for k8s discovery
    if ! setup_port_forwarding; then
        print_error "Failed to setup port forwarding"
        cleanup_resources
        return 1
    fi

    # Run test
    if run_test "$test_type" "$routing_logic"; then
        print_status "✅ $test_type test completed successfully"
    else
        print_error "❌ $test_type test failed"
        collect_debug_logs "$test_type"
        cleanup_resources
        return 1
    fi

    # Collect debug logs
    collect_debug_logs "$test_type"

    print_status "=========================================="
    print_status "$test_type test completed"
    print_status "=========================================="
}

# Function to run all tests
run_all_tests() {
    print_status "🚀 Starting all k8s routing tests"

    # Define all available test types and their configurations
    local test_configs=(
        "roundrobin:roundrobin:.github/values-08-roundrobin-routing.yaml"
        "prefixaware:prefixaware:.github/values-07-prefix-routing.yaml"
        "kvaware:kvaware:.github/values-09-kvaware-routing.yaml"
        "session:session:.github/values-06-session-routing.yaml"
        "disaggregated-prefill:disaggregated_prefill:.github/values-10-disagg-prefill.yaml"
    )

    local failed_tests=()
    local successful_tests=()

    for test_config in "${test_configs[@]}"; do
        IFS=':' read -r test_type routing_logic helm_values_file <<< "$test_config"

        print_status "=========================================="
        print_status "Running $test_type test"
        print_status "=========================================="

        # Run the test
        if run_complete_test "$test_type" "$helm_values_file" "$routing_logic"; then
            print_status "✅ $test_type test passed"
            successful_tests+=("$test_type")
        else
            print_error "❌ $test_type test failed"
            failed_tests+=("$test_type")
        fi

        # Small delay between tests
        sleep 2
    done

    # Report final results
    print_status "=========================================="
    print_status "All Tests Summary"
    print_status "=========================================="

    if [ ${#successful_tests[@]} -gt 0 ]; then
        print_status "✅ Successful tests: ${successful_tests[*]}"
    fi

    if [ ${#failed_tests[@]} -gt 0 ]; then
        print_error "❌ Failed tests: ${failed_tests[*]}"
    fi

    if [ ${#failed_tests[@]} -eq 0 ]; then
        print_status "🎉 All tests passed!"
        return 0
    else
        print_error "💥 Some tests failed"
        return 1
    fi
}

# Parse command line arguments
if [ $# -eq 0 ]; then
    show_usage
    exit 1
fi

# Check if first argument is help
if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    show_usage
    exit 0
fi

# Get test type
TEST_TYPE="$1"
shift

# Parse remaining options
while [[ $# -gt 0 ]]; do
    case $1 in
        -m|--model)
            MODEL="$2"
            shift 2
            ;;
        -r|--num-requests)
            NUM_REQUESTS="$2"
            shift 2
            ;;
        -c|--chunk-size)
            CHUNK_SIZE="$2"
            shift 2
            ;;
        -u|--router-url)
            ROUTER_URL="$2"
            shift 2
            ;;
        -l|--log-file-path)
            LOG_FILE_PATH="$2"
            shift 2
            ;;
        -d|--result-dir)
            RESULT_DIR="$2"
            shift 2
            ;;
        -v|--verbose)
            VERBOSE="true"
            shift
            ;;
        --timeout)
            TIMEOUT_MINUTES="$2"
            shift 2
            ;;
        --session-key)
            SESSION_KEY="$2"
            shift 2
            ;;
        *)
            print_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Run tests based on test type
if [ "$TEST_TYPE" = "all" ]; then
    # Run all tests
    run_all_tests
    cleanup_resources
else
    # Validate test type and set configuration for single test
    case $TEST_TYPE in
        "roundrobin")
            HELM_VALUES_FILE=".github/values-08-roundrobin-routing.yaml"
            ROUTING_LOGIC="roundrobin"
            ;;
        "prefixaware")
            HELM_VALUES_FILE=".github/values-07-prefix-routing.yaml"
            ROUTING_LOGIC="prefixaware"
            ;;
        "kvaware")
            HELM_VALUES_FILE=".github/values-09-kvaware-routing.yaml"
            ROUTING_LOGIC="kvaware"
            ;;
        "disaggregated-prefill")
            HELM_VALUES_FILE=".github/values-10-disagg-prefill.yaml"
            ROUTING_LOGIC="disaggregated_prefill"
            ;;
        "session")
            HELM_VALUES_FILE=".github/values-06-session-routing.yaml"
            ROUTING_LOGIC="session"
            ;;
        *)
            print_error "Invalid test type: $TEST_TYPE"
            print_error "Valid options: roundrobin, prefixaware, kvaware, session, disaggregated-prefill, all"
            exit 1
            ;;
    esac

    # Run single test
    run_complete_test "$TEST_TYPE" "$HELM_VALUES_FILE" "$ROUTING_LOGIC"
    cleanup_resources
fi
