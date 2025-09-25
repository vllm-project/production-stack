#!/bin/bash

set -euo pipefail

echo "⏳ Waiting for backends to be ready"
timeout=${1:-120}
backend1=${2:-"http://localhost:8001"}
backend2=${3:-"http://localhost:8002"}
start_time=$(date +%s)
echo "⏳ Waiting for backends to become reachable..."
while true; do
    current_time=$(date +%s)
    elapsed=$((current_time - start_time))

    if [ $elapsed -ge "$timeout" ]; then
        echo "❌ Backends failed to become reachable after ${timeout} seconds"
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
