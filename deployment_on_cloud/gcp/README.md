# Setting up GKE vLLM stack with one command

This script automatically configures a GKE LLM inference cluster.
Make sure your GCP cli is set up, logged in, and region set up. You have kubectl and helm installed.

Modify fields production_stack_specification.yaml and execute as:

```bash
bash entry_point_basic.sh YAML_FILE_PATH
```

Pods for the vllm deployment should transition to Ready and the Running state.

Expected output:

```plaintext
NAME                                           READY   STATUS    RESTARTS   AGE
vllm-deployment-router-6786bdcc5b-flj2x        1/1     Running   0          54s
vllm-llama3-deployment-vllm-7dd564bc8f-7mf5x   1/1     Running   0          54s
```

Clean up the service with:

```bash
bash clean_up_basic.sh production-stack
```

Note: If you meet up with gpu quota limits, you can try out cpu-version in `gcp/OPT125_CPU`
