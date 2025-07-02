#!/bin/bash

# Simple Router Stress Test
# Tests round-robin routing logic under high concurrent loads

set -euo pipefail

# Default values
ROUTER_PORT=30080
CONCURRENT=200
REQUESTS=1000
LOG_DIR="/tmp/router-stress-logs"
MODEL="facebook/opt-125m"
BACKENDS_URL="http://localhost:8000,http://localhost:8001"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

show_usage() {
    cat << EOF
Router Stress Test - Tests round-robin routing logic

Usage: $0 [options]

Options:
    -c, --concurrent N      Concurrent requests (default: 2000)
    -n, --requests N        Total requests (default: 10000)
    -p, --port PORT         Router port (default: 30080)
    -l, --log-dir DIR       Log directory (default: /tmp/router-stress-logs)
    -m, --model MODEL       Model to use (default: facebook/opt-125m)
    -h, --help              Show this help

Examples:
    $0                      # Basic test (2000 concurrent, 10000 requests)
    $0 -c 500 -n 20000     # High load test
    $0 -p 8080 -c 100      # Different port, lower load

Prerequisites:
    - Router must be started with VLLM_ROUTER_STRESS_TEST_MODE=true
EOF
}

# Check if Apache Bench is available
check_ab() {
    if ! command -v ab >/dev/null 2>&1; then
        print_error "Apache Bench (ab) not found!"
        print_error "Install with: sudo apt-get install apache2-utils"
        exit 1
    fi
}

# Function to cleanup processes
cleanup() {
    print_status "Cleaning up router processes..."
    pkill -f "python3 -m src.vllm_router.app" || true
    sleep 2
}

# Function to start router
start_router() {
    local log_file="$LOG_DIR/router.log"
    
    print_status "Starting router with round-robin routing (stress test mode)"
    
    # Create log directory
    mkdir -p "$(dirname "$log_file")"
    
    # Set stress test mode
    export VLLM_ROUTER_STRESS_TEST_MODE=true
    
    # Start router with detailed logging
    python3 -m src.vllm_router.app --port "$ROUTER_PORT" \
        --service-discovery static \
        --static-backends "$BACKENDS_URL" \
        --static-models "$MODEL,$MODEL" \
        --static-model-types "chat,chat" \
        --routing-logic roundrobin \
        --log-stats \
        --log-stats-interval 5 > "$log_file" 2>&1 &
    
    ROUTER_PID=$!
    print_status "Router started with PID: $ROUTER_PID"
    
    # Wait for router to be ready
    print_status "Waiting for router to be ready..."
    timeout 30 bash -c "until curl -s http://localhost:$ROUTER_PORT/v1/models > /dev/null 2>&1; do sleep 1; done" || {
        print_error "Router failed to start within 30 seconds"
        print_error "Router log:"
        tail -20 "$log_file" || true
        exit 1
    }
    print_status "Router is ready"
}

# Function to run stress test
run_stress_test() {
    print_status "Running stress test with Apache Bench"
    print_status "Concurrent: $CONCURRENT, Total: $REQUESTS"
    
    # Create payload file
    local payload_file="/tmp/stress_payload.json"
    cat > "$payload_file" << EOF
{
    "model": "$MODEL",
    "messages": [
        {"role": "user", "content": "Test message for stress testing"}
    ],
    "max_tokens": 10,
    "temperature": 0.7
}
EOF
    
    # Run Apache Bench
    ab -c "$CONCURRENT" \
       -n "$REQUESTS" \
       -p "$payload_file" \
       -T "application/json" \
       -H "Authorization: Bearer test" \
       -H "x-user-id: stress-test-user" \
       "http://localhost:$ROUTER_PORT/v1/chat/completions"
    
    # Clean up payload file
    rm -f "$payload_file"
    
    print_status "Stress test completed"
    
    # Small delay to ensure all logs are written
    sleep 2
}

# Function to check round-robin correctness
check_roundrobin_correctness() {
    local log_file="$LOG_DIR/router.log"
    
    print_status "Checking round-robin routing correctness..."
    
    if [ ! -f "$log_file" ]; then
        print_error "Router log file not found: $log_file"
        return 1
    fi
    
    # Extract backend routing decisions from logs
    # Look for "Routing request ... to http://localhost:XXXX"
    local backend1_count=$(grep -c "to http://localhost:8000" "$log_file" || echo "0")
    local backend2_count=$(grep -c "to http://localhost:8001" "$log_file" || echo "0")
    local total_routed=$((backend1_count + backend2_count))
    
    print_status "Round-robin routing results:"
    print_status "  Backend localhost:8000: $backend1_count requests"
    print_status "  Backend localhost:8001: $backend2_count requests"
    print_status "  Total routed: $total_routed requests"
    
    if [ "$total_routed" -eq 0 ]; then
        print_error "No routing decisions found in logs"
        return 1
    fi
    
    # Calculate percentages
    local backend1_pct=$((backend1_count * 100 / total_routed))
    local backend2_pct=$((backend2_count * 100 / total_routed))
    
    print_status "  Backend localhost:8000: ${backend1_pct}%"
    print_status "  Backend localhost:8001: ${backend2_pct}%"
    
    # Check if distribution is roughly even (within 20% tolerance)
    local diff=$((backend1_pct > backend2_pct ? backend1_pct - backend2_pct : backend2_pct - backend1_pct))
    
    if [ "$diff" -le 20 ]; then
        print_status "✅ Round-robin routing is working correctly (${diff}% difference)"
        return 0
    else
        print_error "❌ Round-robin routing appears uneven (${diff}% difference)"
        print_status "Last 10 routing decisions from logs:"
        grep "Routing request.*to http://localhost:" "$log_file" | tail -10 | sed 's/^/  /' || true
        return 1
    fi
}

# Function to show log summary
show_log_summary() {
    local log_file="$LOG_DIR/router.log"
    
    if [ -f "$log_file" ]; then
        print_status "Log summary (last 20 lines):"
        tail -20 "$log_file" | sed 's/^/  /'
    fi
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -c|--concurrent)
            CONCURRENT="$2"
            shift 2
            ;;
        -n|--requests)
            REQUESTS="$2"
            shift 2
            ;;
        -p|--port)
            ROUTER_PORT="$2"
            shift 2
            ;;
        -l|--log-dir)
            LOG_DIR="$2"
            shift 2
            ;;
        -m|--model)
            MODEL="$2"
            shift 2
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Set trap for cleanup
trap cleanup EXIT

# Check prerequisites
print_status "Checking prerequisites..."
check_ab

print_status "Router stress test configuration:"
print_status "  Concurrent requests: $CONCURRENT"
print_status "  Total requests: $REQUESTS"
print_status "  Router port: $ROUTER_PORT"
print_status "  Model: $MODEL"

# Run test
start_router
run_stress_test

# Check correctness and show results
if check_roundrobin_correctness; then
    print_status "Test completed successfully!"
else
    print_error "Test completed but round-robin routing correctness check failed!"
    show_log_summary
    exit 1
fi 