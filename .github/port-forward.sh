#!/bin/bash

echo "Waiting for all llmstack pods to be in Running state..."

# Save output
VAR="${1#curl-}"
[ ! -d "output-$VAR" ] && mkdir "output-$VAR"
chmod -R 777 "output-$VAR"

# Print router logs
POD_NAME=$(kubectl get pods --no-headers -o custom-columns=":metadata.name" | grep '^vllm-deployment-router')
kubectl wait --for=condition=ready pod/"$POD_NAME" --timeout=120s
kubectl logs -f "$POD_NAME" 2>&1 | tee "output-$VAR/router.log" &

# Loop to check if all llmstack-related pods are in the Running state
while true; do
    # Check each vllm pod individually
    kubectl get pods --no-headers | grep "vllm" | while read -r line; do
        pod_name=$(echo "$line" | awk '{print $1}')
        status=$(echo "$line" | awk '{print $3}')
        ready=$(echo "$line" | awk '{print $2}')

        # Log timestamp and pod info
        timestamp=$(date '+%Y-%m-%d %H:%M:%S')
        echo "[$timestamp] Checking pod: $pod_name"
        kubectl get events --field-selector involvedObject.name="$pod_name" --sort-by='.lastTimestamp'
        kubectl describe node | grep -C 15 "Allocated resources:"
        if [[ "$status" != "Running" ]] || [[ "$ready" != "1/1" ]]; then
            echo "[$timestamp] Pod $pod_name diagnostics:"
            kubectl describe pod "$pod_name"
            if kubectl get pod "$pod_name" -o jsonpath='{.status.containerStatuses[0].restartCount}' | grep -vq '^0'; then
                kubectl logs "$pod_name" --previous
            else
                kubectl logs "$pod_name"
            fi
            pvc_name=$(kubectl get pod "$pod_name" -o jsonpath='{.spec.volumes[*].persistentVolumeClaim.claimName}')
            if [ -n "$pvc_name" ]; then
                pvc_status=$(kubectl get pvc "$pvc_name" -o jsonpath='{.status.phase}')
                if [[ "$pvc_status" != "Bound" ]]; then
                    echo "[$timestamp] PVC $pvc_name status:"
                    kubectl describe pvc "$pvc_name"
                fi
            fi
        fi
    done

    echo "Not all pods are ready yet. Checking again in 20 seconds..."
    sleep 20
done

# Expose router service
kubectl patch service vllm-router-service -p '{"spec":{"type":"NodePort"}}'
ip=$(minikube ip)
port=$(kubectl get svc vllm-router-service -o=jsonpath='{.spec.ports[0].nodePort}')

sleep 5

bash ".github/$1.sh" "$ip" "$port"
