#!/bin/bash

HOST=$1
PORT=$2

# Make sure prometheus is up and running before sending the query
kubectl wait --for=condition=ready pod/prometheus-vllm-kube-prometheus-stack-prometheus-0 --timeout=60s

kubectl patch service vllm-kube-prometheus-stack-prometheus -p '{"spec":{"type":"NodePort"}}'
PROM_PORT=$(kubectl get svc vllm-kube-prometheus-stack-prometheus -o=jsonpath='{.spec.ports[0].nodePort}')
PROM_URL="http://$HOST:$PROM_PORT"

# Query Prometheus for the 'up' metric of the router service
result_prom=$(curl -s -G "$PROM_URL/api/v1/query" \
    --data-urlencode 'query=up{job="vllm-router-service"} == 1' \
    | jq | tee output-06-monitoring/prometheus-status.json)

if [[ -z "$result_prom" ]]; then
    echo "Error: Prometheus query returned an empty response."
    exit 1
fi

# Verify result contains at least one entry with metric.pod matching the router
router_up_count=$(echo "$result_prom" | jq '[.data.result[] | select(.metric.pod | startswith("vllm-deployment-router"))] | length' 2>/dev/null)
if [[ "$router_up_count" -eq 0 ]]; then
    echo "Error: No UP router pod found in Prometheus results."
    echo "Pods reported: $(echo "$result_prom" | jq -r '[.data.result[].metric.pod] | join(", ")')"
    exit 1
fi

echo "Prometheus ServiceMonitor validation successful: $router_up_count router pod(s) UP."

# Send an initial request to initialize the metric (it may not exist before any request)
curl --connect-timeout 5 -s -X POST http://"$HOST":"$PORT"/v1/completions \
    -H "Content-Type: application/json" \
    -d '{"model": "facebook/opt-125m", "prompt": "Once upon a time,", "max_tokens": 10}' \
    > /dev/null

# Wait for Prometheus to scrape the initialized metric
sleep 10

# Get baseline value
result_prom=$(curl -s -G "$PROM_URL/api/v1/query" \
    --data-urlencode 'query=vllm:num_incoming_requests_total{job="vllm-router-service",model="facebook/opt-125m"}' \
    | jq | tee output-06-monitoring/prometheus-metrics-before.json)

if [[ -z "$result_prom" ]]; then
    echo "Error: Prometheus query returned an empty response."
    exit 1
fi

request_count=$(echo "$result_prom" | jq -r '.data.result[0].value[1]' 2>/dev/null)
echo "Baseline request count: $request_count"

# Send a second request to increment the counter
curl --connect-timeout 5 -s -X POST http://"$HOST":"$PORT"/v1/completions \
    -H "Content-Type: application/json" \
    -d '{"model": "facebook/opt-125m", "prompt": "Once upon a time,", "max_tokens": 10}' \
    > /dev/null

# Wait for Prometheus to scrape the updated metrics
sleep 10

# Query Prometheus again to check if the counter has incremented
result_prom=$(curl --connect-timeout 5 -s -G "$PROM_URL/api/v1/query" \
    --data-urlencode 'query=vllm:num_incoming_requests_total{job="vllm-router-service",model="facebook/opt-125m"}' \
    | jq | tee output-06-monitoring/prometheus-metrics-after.json)

if [[ -z "$result_prom" ]]; then
    echo "Error: Prometheus query returned an empty response."
    exit 1
fi

new_request_count=$(echo "$result_prom" | jq -r '.data.result[0].value[1]' 2>/dev/null)
echo "New request count: $new_request_count"

if ! awk "BEGIN {exit ($new_request_count > $request_count) ? 0 : 1}"; then
    echo "Error: vllm:num_incoming_requests_total did not increment. Previous: $request_count, New: $new_request_count"
    exit 1
fi

echo "Prometheus metrics validation successful: vllm:num_incoming_requests_total incremented from $request_count to $new_request_count."
