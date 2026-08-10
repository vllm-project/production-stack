#!/bin/bash

set -euo pipefail

echo "⏳ Waiting for backends to be ready"
timeout=${1:-120}
backend1=${2:-"http://localhost:8001"}
backend2=${3:-"http://localhost:8002"}
backend1_pid=${4:-}
backend2_pid=${5:-}
backend1_log=${6:-}
backend2_log=${7:-}

print_backend_log() {
    local backend_name=$1
    local log_file=$2

    if [ -n "$log_file" ] && [ -f "$log_file" ]; then
        echo "Last 50 lines from ${backend_name} log (${log_file}):"
        tail -n 50 "$log_file" || true
    fi
    return 0
}

check_backend_process() {
    local backend_name=$1
    local backend_pid=$2
    local log_file=$3

    if [ -n "$backend_pid" ] && ! kill -0 "$backend_pid" 2>/dev/null; then
        echo "❌ ${backend_name} process exited before becoming reachable"
        print_backend_log "$backend_name" "$log_file"
        return 1
    fi
    return 0
}

start_time=$(date +%s)
echo "⏳ Waiting for backends to become reachable..."
while true; do
    current_time=$(date +%s)
    elapsed=$((current_time - start_time))

    check_backend_process "Backend 1" "$backend1_pid" "$backend1_log" || exit 1
    check_backend_process "Backend 2" "$backend2_pid" "$backend2_log" || exit 1

    if [ $elapsed -ge "$timeout" ]; then
        echo "❌ Backends failed to become reachable after ${timeout} seconds"
        print_backend_log "Backend 1" "$backend1_log"
        print_backend_log "Backend 2" "$backend2_log"
        exit 1
    fi

    echo "⏳ Checking backend readiness (${elapsed}s elapsed)..."
    if curl -s --connect-timeout 5 "${backend1}" > /dev/null 2>&1 && \
        curl -s --connect-timeout 5 "${backend2}" > /dev/null 2>&1; then
        echo "✅ Both backends are reachable!"
        break
    fi

    echo "⏳ Backends are not reachable yet. Check again in 5 seconds..."
    sleep 5
done
