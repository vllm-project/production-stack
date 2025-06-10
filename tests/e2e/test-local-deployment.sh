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

# Configuration
ROUTER_PORT=8080
VLLM_PORT=8000
MODEL="meta-llama/Llama-3.2-1B-Instruct"
ROUTER_PID=""
VLLM_PID=""

# Function to install uv if not available
install_uv() {
    print_status "uv not found, installing uv..."

    # Check if curl is available
    if command -v curl &> /dev/null; then
        print_status "Installing uv using curl..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget &> /dev/null; then
        print_status "Installing uv using wget..."
        wget -qO- https://astral.sh/uv/install.sh | sh
    else
        print_error "Neither curl nor wget is available. Cannot install uv automatically."
        print_error "Please install uv manually: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi

    # Source the shell to make uv available in current session
    if [ -f "$HOME/.cargo/env" ]; then
        # shellcheck source=/dev/null
        source "$HOME/.cargo/env"
    fi

    # Add uv to PATH if it's in the default location
    if [ -d "$HOME/.cargo/bin" ] && [[ ":$PATH:" != *":$HOME/.cargo/bin:"* ]]; then
        export PATH="$HOME/.cargo/bin:$PATH"
    fi

    # Verify installation
    if ! command -v uv &> /dev/null; then
        print_error "❌ uv installation failed or not in PATH"
        print_error "Please ensure uv is properly installed and in your PATH"
        exit 1
    fi

    print_status "✅ uv installed successfully"
}

# Function to setup Python environment
setup_environment() {
    print_status "Setting up Python environment..."

    # Check if uv is available, install if not
    if ! command -v uv &> /dev/null; then
        install_uv
    else
        print_status "✅ uv is already available"
    fi

    # Check if .venv already exists and is valid
    if [ -d ".venv" ] && [ -f ".venv/pyvenv.cfg" ]; then
        print_status "Virtual environment already exists, checking if it's up to date..."

        # Activate the environment and check if vllm is installed
        if .venv/bin/python -c "import vllm" 2>/dev/null; then
            print_status "✅ Environment appears to be ready"
            return 0
        else
            print_status "Environment exists but missing dependencies, reinstalling..."
            rm -rf .venv
        fi
    fi

    print_status "Creating virtual environment with uv..."
    uv venv .venv

    print_status "Installing project dependencies..."
    uv pip install -e ".[semantic_cache]" --python .venv/bin/python

    print_status "Installing vLLM..."
    uv pip install vllm --python .venv/bin/python

    print_status "Installing test dependencies..."
    uv pip install -r requirements-test.txt --python .venv/bin/python

    # Verify installation
    if .venv/bin/python -c "import vllm; import vllm_router" 2>/dev/null; then
        print_status "✅ Environment setup completed successfully"
    else
        print_error "❌ Environment setup failed - missing required packages"
        exit 1
    fi
}

# Cleanup function
cleanup() {
    print_status "Cleaning up processes..."

    if [ -n "$ROUTER_PID" ]; then
        print_status "Stopping router (PID: $ROUTER_PID)"
        kill "$ROUTER_PID" 2>/dev/null || true
        wait "$ROUTER_PID" 2>/dev/null || true
    fi

    if [ -n "$VLLM_PID" ]; then
        print_status "Stopping vLLM server (PID: $VLLM_PID)"
        kill "$VLLM_PID" 2>/dev/null || true
        wait "$VLLM_PID" 2>/dev/null || true
    fi

    print_status "Cleanup completed"
}

# Set up cleanup trap
trap cleanup EXIT

# Function to wait for service to be ready
wait_for_service() {
    local url=$1
    local service_name=$2
    local max_attempts=30
    local attempt=1

    print_status "Waiting for $service_name to be ready at $url..."

    while [ $attempt -le $max_attempts ]; do
        if curl -s "$url" > /dev/null 2>&1; then
            print_status "✅ $service_name is ready!"
            return 0
        fi

        print_status "Attempt $attempt/$max_attempts: $service_name not ready yet, waiting..."
        sleep 5
        attempt=$((attempt + 1))
    done

    print_error "❌ $service_name failed to become ready after $max_attempts attempts"
    return 1
}

# Function to test endpoints
test_endpoint() {
    local url=$1
    local description=$2
    local expected_status=${3:-200}

    print_status "Testing: $description"
    print_status "URL: $url"

    local response
    local http_code

    response=$(curl -s -w "\n%{http_code}" "$url" 2>/dev/null || echo -e "\nERROR")
    http_code=$(echo "$response" | tail -n1)
    local body
    body=$(echo "$response" | head -n -1)

    if [ "$http_code" = "ERROR" ]; then
        print_error "❌ Request failed - connection error"
        return 1
    elif [ "$http_code" -eq "$expected_status" ]; then
        print_status "✅ Success (HTTP $http_code)"
        if [ -n "$body" ] && [ "$body" != "null" ]; then
            echo "Response preview:"
            echo "$body" | head -c 200
            if [ ${#body} -gt 200 ]; then
                echo "..."
            fi
            echo ""
        fi
        return 0
    else
        print_error "❌ Failed (HTTP $http_code, expected $expected_status)"
        if [ -n "$body" ]; then
            echo "Response:"
            echo "$body"
        fi
        return 1
    fi
}

# Function to test completions endpoint
test_completions() {
    local base_url=$1
    local service_name=$2

    print_status "Testing $service_name completions endpoint..."

    local response
    response=$(curl -s -X POST "$base_url/v1/completions" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer dummy" \
        -d '{
            "model": "'"$MODEL"'",
            "prompt": "Hello, how are you?",
            "max_tokens": 50,
            "temperature": 0.7
        }' 2>/dev/null || echo "ERROR")

    if [ "$response" = "ERROR" ]; then
        print_error "❌ $service_name completions request failed"
        return 1
    fi

    # Check if response contains expected fields
    if echo "$response" | jq -e '.choices[0].text' > /dev/null 2>&1; then
        print_status "✅ $service_name completions working"
        local text
        text=$(echo "$response" | jq -r '.choices[0].text' | head -c 100)
        echo "Generated text preview: $text"
        return 0
    else
        print_error "❌ $service_name completions response invalid"
        echo "Response: $response"
        return 1
    fi
}

# Function to test chat completions endpoint
test_chat_completions() {
    local base_url=$1
    local service_name=$2

    print_status "Testing $service_name chat completions endpoint..."

    local response
    response=$(curl -s -X POST "$base_url/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer dummy" \
        -d '{
            "model": "'"$MODEL"'",
            "messages": [{"role": "user", "content": "Hello, how are you?"}],
            "max_tokens": 50,
            "temperature": 0.7
        }' 2>/dev/null || echo "ERROR")

    if [ "$response" = "ERROR" ]; then
        print_error "❌ $service_name chat completions request failed"
        return 1
    fi

    # Check if response contains expected fields
    if echo "$response" | jq -e '.choices[0].message.content' > /dev/null 2>&1; then
        print_status "✅ $service_name chat completions working"
        local content
        content=$(echo "$response" | jq -r '.choices[0].message.content' | head -c 100)
        echo "Generated content preview: $content"
        return 0
    else
        print_error "❌ $service_name chat completions response invalid"
        echo "Response: $response"
        return 1
    fi
}

# Main execution
print_status "Starting local deployment test..."
print_status "Router port: $ROUTER_PORT"
print_status "vLLM port: $VLLM_PORT"
print_status "Model: $MODEL"

# Check if required commands exist
for cmd in curl jq python3; do
    if ! command -v "$cmd" &> /dev/null; then
        print_error "Required command '$cmd' not found"
        exit 1
    fi
done

# Set up Python environment
setup_environment

# Check if HF_TOKEN is set
if [ -z "${HF_TOKEN:-}" ]; then
    print_error "HF_TOKEN environment variable is not set"
    print_error "Please set it with: export HF_TOKEN=your_token_here"
    print_error "You can get a token from: https://huggingface.co/settings/tokens"
    exit 1
fi

# Start vLLM server
print_status "Starting vLLM server on port $VLLM_PORT..."
VLLM_LOG_FILE="vllm_server.log"
# Use the virtual environment's vllm explicitly
HF_TOKEN="$HF_TOKEN" .venv/bin/python -m vllm.entrypoints.openai.api_server --model "$MODEL" --port $VLLM_PORT --disable-log-requests --enforce-eager > "$VLLM_LOG_FILE" 2>&1 &
VLLM_PID=$!
print_status "vLLM server started with PID: $VLLM_PID"
print_status "vLLM logs: $VLLM_LOG_FILE"

# Wait for vLLM server to be ready
if ! wait_for_service "http://localhost:$VLLM_PORT/v1/models" "vLLM server"; then
    print_error "vLLM server failed to start"
    print_error "Check vLLM logs for details:"
    print_error "tail -50 $VLLM_LOG_FILE"
    echo ""
    print_error "Last 20 lines of vLLM log:"
    tail -20 "$VLLM_LOG_FILE" 2>/dev/null || echo "Could not read log file"
    exit 1
fi

# Start router
print_status "Starting router on port $ROUTER_PORT..."
ROUTER_LOG_FILE="router.log"
cd src/vllm_router
python3 -m vllm_router.app --port $ROUTER_PORT \
    --service-discovery static \
    --static-backends "http://localhost:8000" \
    --static-models "$MODEL" \
    --static-model-types "chat" \
    --log-stats \
    --log-stats-interval 10 \
    --engine-stats-interval 10 \
    --request-stats-window 10 \
    --routing-logic roundrobin > "../$ROUTER_LOG_FILE" 2>&1 &
ROUTER_PID=$!
cd - > /dev/null
print_status "Router started with PID: $ROUTER_PID"
print_status "Router logs: router.log"

# Wait for router to be ready
if ! wait_for_service "http://localhost:$ROUTER_PORT/health" "Router"; then
    print_warning "Router health endpoint not available, trying models endpoint..."
    if ! wait_for_service "http://localhost:$ROUTER_PORT/v1/models" "Router"; then
        print_error "Router failed to start"
        exit 1
    fi
fi

print_status "🚀 Both services are running! Starting tests..."

# Test direct vLLM server endpoints
print_status "\n=== Testing Direct vLLM Server ==="

test_endpoint "http://localhost:$VLLM_PORT/v1/models" "vLLM models endpoint"
test_completions "http://localhost:$VLLM_PORT" "vLLM"
test_chat_completions "http://localhost:$VLLM_PORT" "vLLM"

# Test router endpoints
print_status "\n=== Testing Router ==="

test_endpoint "http://localhost:$ROUTER_PORT/v1/models" "Router models endpoint"
test_completions "http://localhost:$ROUTER_PORT" "Router"
test_chat_completions "http://localhost:$ROUTER_PORT" "Router"

# Additional router-specific tests
print_status "\n=== Additional Router Tests ==="

# Test with session header
print_status "Testing router with session header..."
response=$(curl -s -X POST "http://localhost:$ROUTER_PORT/v1/completions" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer dummy" \
    -H "x-user-id: test-session-123" \
    -d '{
        "model": "'"$MODEL"'",
        "prompt": "Session test prompt",
        "max_tokens": 20,
        "temperature": 0.1
    }' 2>/dev/null || echo "ERROR")

if [ "$response" != "ERROR" ] && echo "$response" | jq -e '.choices[0].text' > /dev/null 2>&1; then
    print_status "✅ Router session header test passed"
else
    print_error "❌ Router session header test failed"
fi

print_status "\n🎉 All tests completed successfully!"
print_status "Cleaning up and exiting..."

# Exit cleanly - the cleanup function will be called automatically due to the EXIT trap
