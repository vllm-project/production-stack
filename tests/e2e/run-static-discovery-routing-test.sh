#!/bin/bash

# Script to run routing tests with different routing logic
# Usage: ./run-routing-test.sh <routing_logic> [options]

set -euo pipefail

# Default values
ROUTING_LOGIC="roundrobin"
ROUTER_PORT=30080
LOG_DIR="/tmp/router-logs"
NUM_REQUESTS=20
MODEL="facebook/opt-125m"
BACKEND1="http://localhost:8001"
BACKEND2="http://localhost:8002"
PYTHONPATH=""
VERBOSE=""

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
Usage: $0 <routing_logic> [options]

Routing Logic Options:
    roundrobin          - Test round-robin routing
    prefixaware         - Test prefix-aware routing
    kvaware            - Test KV-aware routing
    disaggregated_prefill - Test disaggregated prefill routing

Options:
    -p, --port PORT         Router port (default: 30080)
    -l, --log-dir DIR       Log directory (default: /tmp/router-logs)
    -n, --num-requests N    Number of requests to test (default: 20)
    -m, --model MODEL       Model to use (default: facebook/opt-125m)
    -b1, --backend1 URL     First backend URL (default: http://localhost:8001)
    -b2, --backend2 URL     Second backend URL (default: http://localhost:8002)
    -v, --verbose           Enable verbose output
    -h, --help              Show this help message

Examples:
    $0 roundrobin
    $0 prefixaware --num-requests 30 --verbose
    $0 kvaware --port 30081 --log-dir ./logs

EOF
}

# Function to cleanup processes
cleanup() {
    print_status "Cleaning up router processes..."
    pkill -f "python3 -m src.vllm_router.app" || true
    sleep 2
}

# Function to start router
start_router() {
    local routing_logic=$1
    local log_file="$LOG_DIR/$routing_logic/router.log"

    print_status "🔧 Starting router with static discovery and $routing_logic routing"
    print_status "PYTHONPATH=$PYTHONPATH"

    # Create log directory
    mkdir -p "$(dirname "$log_file")"

    # Start router in background with log capture
    python3 -m src.vllm_router.app --port "$ROUTER_PORT" \
        --service-discovery static \
        --static-backends "$BACKEND1,$BACKEND2" \
        --static-models "$MODEL,$MODEL" \
        --static-model-types "chat,chat" \
        --log-stats \
        --log-stats-interval 10 \
        --engine-stats-interval 10 \
        --request-stats-window 10 \
        --routing-logic "$routing_logic" > "$log_file" 2>&1 &

    ROUTER_PID=$!
    print_status "Router started with PID: $ROUTER_PID"

    # Check if router is running
    print_status "Waiting for router to be ready..."
    timeout 30 bash -c "until curl -s http://localhost:$ROUTER_PORT > /dev/null 2>&1; do sleep 1; done" || {
        print_error "❌ Router failed to start within 30 seconds"
        print_error "Router log:"
        tail -20 "$log_file" || true
        exit 1
    }
    print_status "✅ Router started successfully"
}

# Function to run test
run_test() {
    local routing_logic=$1
    local log_file="$LOG_DIR/$routing_logic/router.log"
    local result_dir="$LOG_DIR/$routing_logic"

    print_status "🧪 Running static discovery test for $routing_logic routing"

    # Build test command
    local test_cmd="python3 tests/e2e/test-static-discovery.py"
    test_cmd="$test_cmd --num-requests $NUM_REQUESTS"
    test_cmd="$test_cmd --log-file-path '$log_file'"
    test_cmd="$test_cmd --router-url http://localhost:$ROUTER_PORT"
    test_cmd="$test_cmd --routing-logic $routing_logic"
    test_cmd="$test_cmd --result-dir '$result_dir'"

    if [ "$VERBOSE" = "true" ]; then
        test_cmd="$test_cmd --verbose"
    fi

    # Run the test
    print_status "Executing: $test_cmd"
    if eval "$test_cmd"; then
        print_status "✅ Test for $routing_logic routing completed successfully"
        return 0
    else
        print_error "❌ Test for $routing_logic routing failed"
        return 1
    fi
}

# Function to run multiple routing tests
run_multiple_tests() {
    local routing_logics=("$@")
    local failed_tests=()

    for logic in "${routing_logics[@]}"; do
        print_status "=========================================="
        print_status "Testing $logic routing"
        print_status "=========================================="

        # Start router
        start_router "$logic"

        # Run test
        if run_test "$logic"; then
            print_status "✅ $logic test passed"
        else
            print_error "❌ $logic test failed"
            failed_tests+=("$logic")
        fi

        # Cleanup
        cleanup

        # Small delay between tests
        sleep 1
    done

    # Report results
    print_status "=========================================="
    print_status "Test Results Summary"
    print_status "=========================================="

    if [ ${#failed_tests[@]} -eq 0 ]; then
        print_status "✅ All tests passed!"
        return 0
    else
        print_error "❌ Failed tests: ${failed_tests[*]}"
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

# Get routing logic
ROUTING_LOGIC="$1"
shift

# Parse remaining options
while [[ $# -gt 0 ]]; do
    case $1 in
        -p|--port)
            ROUTER_PORT="$2"
            shift 2
            ;;
        -l|--log-dir)
            LOG_DIR="$2"
            shift 2
            ;;
        -n|--num-requests)
            NUM_REQUESTS="$2"
            shift 2
            ;;
        -m|--model)
            MODEL="$2"
            shift 2
            ;;
        -b1|--backend1)
            BACKEND1="$2"
            shift 2
            ;;
        -b2|--backend2)
            BACKEND2="$2"
            shift 2
            ;;
        -v|--verbose)
            VERBOSE="true"
            shift
            ;;
        --pythonpath)
            PYTHONPATH="$2"
            shift 2
            ;;
        *)
            print_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Validate routing logic
valid_logics=("roundrobin" "prefixaware" "all")
if [[ ! " ${valid_logics[*]} " =~ ${ROUTING_LOGIC} ]]; then
    print_error "Invalid routing logic: $ROUTING_LOGIC"
    print_error "Valid options: ${valid_logics[*]}"
    exit 1
fi

# Set trap for cleanup
trap cleanup EXIT

# Export PYTHONPATH if provided
if [ -n "$PYTHONPATH" ]; then
    export PYTHONPATH
fi

# Run tests based on routing logic
if [ "$ROUTING_LOGIC" = "all" ]; then
    # Run all tests
    all_logics=("roundrobin" "prefixaware")
    run_multiple_tests "${all_logics[@]}"
else
    # Run single test
    start_router "$ROUTING_LOGIC"
    run_test "$ROUTING_LOGIC"
    cleanup
fi
