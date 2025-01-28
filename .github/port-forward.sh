#!/bin/bash

# Ensure the script is run with root privileges
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (use sudo)." 
   exit 1
fi

echo "Waiting for all llmstack pods to be in Running state..."

# Loop to check if all llmstack-related pods are in the Running state
while true; do
    # Get all pods containing "llmstack" in their name and extract their STATUS column
    pod_status=$(kubectl get pods --no-headers | grep "vllm" | awk '{print $3}' | sort | uniq)

    # If the only unique status is "Running", break the loop and continue
    if [[ "$pod_status" == "Running" ]]; then
        echo "All llmstack pods are now in Running state."
        break
    fi

    echo "Not all pods are ready yet. Checking again in 5 seconds..."
    sleep 5
done

# Start port-forwarding once all pods are running
echo "Starting port-forwarding..."
sudo kubectl port-forward svc/vllm-router-service 30080:80 &
