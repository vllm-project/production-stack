#!/bin/bash

# Ensure the script is run with root privileges
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (use sudo)." 
   exit 1
fi

echo "Waiting for all llmstack pods to be in Running state..."

# Loop to check if all llmstack-related pods are in the Running state
while true; do
    # Get all pods containing "vllm" in their name and extract their STATUS column
    pod_status=$(sudo kubectl get pods --no-headers | grep "vllm" | awk '{print $3}' | sort | uniq)
    pod_ready=$(sudo kubectl get pods --no-headers | grep "vllm" | awk '{print $2}' | sort | uniq)

    # If the only unique status is "Running", break the loop and continue
    if [[ "$pod_status" == "Running" ]] and [[ "$pod_ready" == "1/1" ]]; then
        echo "All llmstack pods are now Ready and in Running state."
        break
    fi

    echo "Not all pods are ready yet. Checking again in 5 seconds..."
    sleep 5
done

port1=30080
max_port=30090
while [ $port1 -le $max_port ]; do
    netstat -tuln | grep ":$port1 " > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo "Port $port1 is available."
        break
    else
        echo "Port $port1 is in use, trying next..."
        port1=$((port1 + 1))
    fi
done

# Start port-forwarding once all pods are running
echo "Starting port-forwarding..."
sudo kubectl port-forward svc/vllm-router-service $port1:80 &

sleep 10
[ ! -d "output" ] && mkdir output
result_model=$(curl -s http://localhost:$port1/models | tee ../output/models.json)
result_query=$(curl -X POST http://localhost:$port1/completions -H "Content-Type: application/json" -d '{"model": "facebook/opt-125m", "prompt": "Once upon a time,", "max_tokens": 10}' | tee ../output/query.json)
