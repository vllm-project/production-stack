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
    if [[ "$pod_status" == "Running" ]] && [[ "$pod_ready" == "1/1" ]]; then
        echo "All llmstack pods are now Ready and in Running state."
        break
    fi

    echo "Not all pods are ready yet. Checking again in 5 seconds..."
    sleep 5
done

# Expose router service
sudo kubectl patch service vllm-router-service -p '{"spec":{"type":"NodePort"}}'
ip=$(sudo minikube ip)
port=$(sudo kubectl get svc vllm-router-service -o=jsonpath='{.spec.ports[0].nodePort}')

bash ".github/$1.sh" "$ip" "$port"
