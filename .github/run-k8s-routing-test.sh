#!/bin/bash

# Script to run k8s routing tests with different routing logic
# Usage: ./run-k8s-routing-test.sh <test_type> [options]

set -euo pipefail

# Default values
TEST_TYPE=""
HELM_VALUES_FILE=""
TEST_SCRIPT=""
TEST_ARGS=""
MODEL="facebook/opt-125m"
NUM_ROUNDS=3
NUM_REQUESTS_PER_SAMPLE=3
CHUNK_SIZE=128
VERBOSE=""
DEBUG=""
TIMEOUT_MINUTES=10

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
    session      - Test sticky routing with session management
    prefixaware        - Test prefix-aware routing
    kvaware           - Test KV-aware routing
    disaggregated-prefill - Test disaggregated prefill routing
    roundrobin         - Test round-robin routing
    all               - Run all available tests sequentially

Options:
    -m, --model MODEL           Model to use (default: facebook/opt-125m)
    -n, --num-rounds N          Number of rounds for sticky routing (default: 3)
    -r, --num-requests N        Number of requests per sample (default: 3)
    -c, --chunk-size N          Chunk size for prefix-aware routing (default: 128)
    -v, --verbose               Enable verbose output
    -d, --debug                 Enable debug mode
    -t, --timeout N             Timeout in minutes (default: 10)
    -h, --help                  Show this help message

Examples:
    $0 session --model "facebook/opt-125m" --num-rounds 5 --verbose
    $0 prefixaware --model "facebook/opt-125m" --chunk-size 256 --debug
    $0 session --verbose --debug
    $0 all --verbose --debug

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
    chmod +x .github/wait-for-pods.sh
    ./.github/wait-for-pods.sh --pod-prefix vllm --timeout 300 --verbose
}

# Function to run test
run_test() {
    local test_type=$1
    local test_script=$2
    local test_args=$3
    
    print_status "🧪 Running $test_type test"
    
    # Make test script executable
    chmod +x "$test_script"
    
    # Build test command
    local test_cmd=""
    case $test_type in
        "session")
            test_cmd="./$test_script --model \"$MODEL\" --num-rounds $NUM_ROUNDS"
            ;;
        "prefixaware")
            test_cmd="python $test_script --model \"$MODEL\" --num-requests-per-sample $NUM_REQUESTS_PER_SAMPLE --chunk-size $CHUNK_SIZE"
            ;;
        "roundrobin")
            test_cmd="python $test_script --model \"$MODEL\" --num-requests-per-sample $NUM_REQUESTS_PER_SAMPLE"
            ;;
        "kvaware")
            test_cmd="python $test_script --model \"$MODEL\" --num-requests-per-sample $NUM_REQUESTS_PER_SAMPLE"
            ;;
        "disaggregated-prefill")
            test_cmd="python $test_script --model \"$MODEL\" --num-requests-per-sample $NUM_REQUESTS_PER_SAMPLE"
            ;;
        *)
            test_cmd="python $test_script"
            ;;
    esac
    
    # Add common arguments
    if [ "$VERBOSE" = "true" ]; then
        test_cmd="$test_cmd --verbose"
    fi
    
    if [ "$DEBUG" = "true" ]; then
        test_cmd="$test_cmd --debug"
    fi
    
    # Add custom test arguments
    if [ -n "$test_args" ]; then
        test_cmd="$test_cmd $test_args"
    fi
    
    print_status "Executing: $test_cmd"
    timeout ${TIMEOUT_MINUTES}m bash -c "$test_cmd"
}

# Function to collect debug logs
collect_debug_logs() {
    local test_type=$1
    print_status "📋 Collecting logs for debugging"
    mkdir -p debug-logs
    # Get router logs
    kubectl logs -l app.kubernetes.io/component=router --tail=100 > debug-logs/router.log || true
    # Get serving engine logs
    kubectl logs -l app.kubernetes.io/component=serving-engine --tail=100 > debug-logs/serving-engines.log || true
    # Get pod status
    kubectl get pods -o wide > debug-logs/pod-status.txt || true
    # Get services
    kubectl get svc > debug-logs/services.txt || true
}

# Function to cleanup resources
cleanup_resources() {
    print_status "🧹 Cleaning up resources"
    helm uninstall vllm || true
    sudo docker image prune -f || true
}

# Function to run complete test
run_complete_test() {
    local test_type=$1
    local helm_values_file=$2
    local test_script=$3
    local test_args=$4
    
    print_status "=========================================="
    print_status "Starting $test_type test"
    print_status "=========================================="
    
    # Deploy helm chart
    deploy_helm_chart "$helm_values_file"
    
    # Wait for pods
    wait_for_pods
    
    # Run test
    if run_test "$test_type" "$test_script" "$test_args"; then
        print_status "✅ $test_type test completed successfully"
    else
        print_error "❌ $test_type test failed"
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
    
    # Define all available test types
    local all_test_types=("session" "prefixaware" "roundrobin" "kvaware" "disaggregated-prefill")
    local failed_tests=()
    local successful_tests=()
    
    for test_type in "${all_test_types[@]}"; do
        print_status "=========================================="
        print_status "Running $test_type test"
        print_status "=========================================="
        
        # Set configuration for this test type
        case $test_type in
            "session")
                local helm_values_file=".github/values-06-session-routing.yaml"
                local test_script="tests/e2e/test-sticky-routing.sh"
                ;;
            "prefixaware")
                local helm_values_file=".github/values-07-prefix-routing.yaml"
                local test_script="tests/e2e/test-prefix-aware-routing.py"
                ;;
            "roundrobin")
                local helm_values_file=".github/values-08-round-robin-routing.yaml"
                local test_script="tests/e2e/test-round-robin-routing.py"
                ;;
            "kvaware")
                local helm_values_file=".github/values-09-kv-aware-routing.yaml"
                local test_script="tests/e2e/test-kv-aware-routing.py"
                ;;
            "disaggregated-prefill")
                local helm_values_file=".github/values-10-disaggregated-prefill-routing.yaml"
                local test_script="tests/e2e/test-disaggregated-prefill-routing.py"
                ;;
            *)
                print_warning "Unknown test type: $test_type, skipping"
                continue
                ;;
        esac
        
        # Run the test
        if run_complete_test "$test_type" "$helm_values_file" "$test_script" ""; then
            print_status "✅ $test_type test passed"
            successful_tests+=("$test_type")
        else
            print_error "❌ $test_type test failed"
            failed_tests+=("$test_type")
        fi
        
        # Small delay between tests
        sleep 5
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
        -n|--num-rounds)
            NUM_ROUNDS="$2"
            shift 2
            ;;
        -r|--num-requests)
            NUM_REQUESTS_PER_SAMPLE="$2"
            shift 2
            ;;
        -c|--chunk-size)
            CHUNK_SIZE="$2"
            shift 2
            ;;
        -v|--verbose)
            VERBOSE="true"
            shift
            ;;
        -d|--debug)
            DEBUG="true"
            shift
            ;;
        -t|--timeout)
            TIMEOUT_MINUTES="$2"
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
        "session")
            HELM_VALUES_FILE=".github/values-06-session-routing.yaml"
            TEST_SCRIPT="tests/e2e/test-sticky-routing.sh"
            ;;
        "prefixaware")
            HELM_VALUES_FILE=".github/values-07-prefix-routing.yaml"
            TEST_SCRIPT="tests/e2e/test-prefix-aware-routing.py"
            ;;
        "kvaware")
            HELM_VALUES_FILE=".github/values-09-kv-aware-routing.yaml"
            TEST_SCRIPT="tests/e2e/test-kv-aware-routing.py"
            ;;
        "disaggregated-prefill")
            print_warning "Disaggregated prefill routing test not yet implemented"
            exit 1
            ;;
        "roundrobin")
            HELM_VALUES_FILE=".github/values-08-round-robin-routing.yaml"
            TEST_SCRIPT="tests/e2e/test-round-robin-routing.py"
            ;;
        *)
            print_error "Invalid test type: $TEST_TYPE"
            print_error "Valid options: session, prefixaware, kvaware, disaggregated-prefill, roundrobin, all"
            exit 1
            ;;
    esac
    
    # Run single test
    run_complete_test "$TEST_TYPE" "$HELM_VALUES_FILE" "$TEST_SCRIPT" "" 
    cleanup_resources