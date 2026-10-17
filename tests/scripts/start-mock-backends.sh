#!/bin/bash
# Start two mock OpenAI-compatible backends for static-discovery e2e tests.
# Usage: eval "$(tests/scripts/start-mock-backends.sh PORT1 PORT2 [speed] [log_dir])"

set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <port1> <port2> [speed] [log_dir]" >&2
    exit 1
fi

PORT1=$1
PORT2=$2
SPEED=${3:-500}
LOG_DIR=${4:-/tmp/mock-backends}

mkdir -p "$LOG_DIR"
PERF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../src/tests/perftest" && pwd)"

cd "$PERF_DIR"
python3 ./fake-openai-server.py --port "$PORT1" --speed "$SPEED" \
    >"$LOG_DIR/backend1.log" 2>&1 &
BACKEND_1_PID=$!
python3 ./fake-openai-server.py --port "$PORT2" --speed "$SPEED" \
    >"$LOG_DIR/backend2.log" 2>&1 &
BACKEND_2_PID=$!

echo "export STATIC_BACKEND_1_PID=${BACKEND_1_PID}"
echo "export STATIC_BACKEND_2_PID=${BACKEND_2_PID}"
