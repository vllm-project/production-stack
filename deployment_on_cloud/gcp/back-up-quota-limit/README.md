# Setting up GKE vLLM stack with one command

This script automatically configures a GKE LLM inference cluster.
Make sure your GCP cli is set up, logged in, and region set up. You have eksctl, kubectl, helm installed.

Modify fields production_stack_specification.yaml and execute as:

```bash
sudo bash entry_point.sh YAML_FILE_PATH
```

Pods for the vllm deployment should transition to Ready and the Running state.

Expected output:

```plaintext
NAME                                            READY   STATUS    RESTARTS   AGE
vllm-deployment-router-69b7f9748d-xrkvn         1/1     Running   0          75s
vllm-opt125m-deployment-vllm-696c998c6f-mvhg4   1/1     Running   0          75s
```

Clean up the service with:

```bash
bash clean_up.sh production-stack
```
