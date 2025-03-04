#!/bin/bash

set -e

# Delete the example resources
echo "Deleting the vllm_router and StaticRoute..."
kubectl delete -k examples/

# Delete the controller
echo "Deleting the StaticRoute controller..."
cd ..
make undeploy
