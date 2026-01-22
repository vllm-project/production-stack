# OCI Data Science Model Deployment

This guide covers deploying vLLM using OCI Data Science Model Deployment as an alternative to OKE-based deployment. OCI Data Science provides a managed infrastructure for model serving with built-in scaling, monitoring, and security.

## Overview

OCI Data Science Model Deployment offers:
- Managed infrastructure (no cluster management)
- Automatic scaling based on load
- Built-in monitoring and logging
- Integration with OCI Identity for authentication
- Support for GPU shapes including A10, A100, and H100

## Prerequisites

- OCI Data Science notebook session or local environment with:
  - [OCI SDK for Python](https://docs.oracle.com/en-us/iaas/tools/python/latest/)
  - [Oracle ADS SDK](https://accelerated-data-science.readthedocs.io/)
- GPU quota for Model Deployment shapes
- Model artifacts in OCI Object Storage or Model Catalog

## Step 1: Prepare Model Artifacts

### Option A: Use Hugging Face Model Directly

Create a score.py that downloads from Hugging Face:

```python
# score.py
import os
from vllm import LLM, SamplingParams

model = None

def load_model():
    global model
    model_name = os.environ.get("MODEL_NAME", "meta-llama/Llama-3.1-8B-Instruct")
    model = LLM(
        model=model_name,
        trust_remote_code=True,
        max_model_len=4096,
        gpu_memory_utilization=0.90
    )

def predict(data):
    if model is None:
        load_model()

    prompts = data.get("prompts", [])
    params = SamplingParams(
        temperature=data.get("temperature", 0.7),
        max_tokens=data.get("max_tokens", 256)
    )

    outputs = model.generate(prompts, params)
    return [{"text": o.outputs[0].text} for o in outputs]
```

### Option B: Use OCI Object Storage

Upload model to Object Storage and use PAR URL:

```python
# score.py
import os
import tarfile
import urllib.request
from vllm import LLM, SamplingParams

model = None
MODEL_DIR = "/home/datascience/models"

def download_model():
    par_url = os.environ["MODEL_PAR_URL"]
    model_name = os.environ["MODEL_NAME"]
    archive_path = f"{MODEL_DIR}/{model_name}.tar.gz"

    os.makedirs(MODEL_DIR, exist_ok=True)
    urllib.request.urlretrieve(par_url, archive_path)

    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(MODEL_DIR)

    return f"{MODEL_DIR}/{model_name}"

def load_model():
    global model
    model_path = download_model()
    model = LLM(
        model=model_path,
        trust_remote_code=True,
        max_model_len=4096,
        gpu_memory_utilization=0.90
    )

def predict(data):
    if model is None:
        load_model()

    prompts = data.get("prompts", [])
    params = SamplingParams(
        temperature=data.get("temperature", 0.7),
        max_tokens=data.get("max_tokens", 256)
    )

    outputs = model.generate(prompts, params)
    return [{"text": o.outputs[0].text} for o in outputs]
```

## Step 2: Create Custom Container Image (BYOC)

There are two deployment approaches:

**Approach A: Bring Your Own Container (BYOC)** - Use the vLLM OpenAI-compatible server directly (recommended for most use cases)

**Approach B: Model Artifacts with score.py** - Use the OCI Data Science native scoring format (see score.py examples above)

### BYOC Deployment (Recommended)

Build and push a vLLM container to OCIR:

```dockerfile
# Dockerfile
FROM vllm/vllm-openai:latest

# Install OCI SDK for authentication
RUN pip install oci oracle-ads

# Set entrypoint for vLLM OpenAI-compatible API server
ENTRYPOINT ["python", "-m", "vllm.entrypoints.openai.api_server"]
```

Push to OCIR:

```bash
docker build -t iad.ocir.io/<tenancy>/vllm-ds:latest .
docker push iad.ocir.io/<tenancy>/vllm-ds:latest
```

## Step 3: Deploy Using ADS SDK

Use the `deploy_model.py` script:

```python
# deploy_model.py
import ads
from ads.model.deployment import ModelDeployment, ModelDeploymentContainerRuntime

# Initialize ADS
ads.set_auth(auth="resource_principal")  # Use instance principal in OCI
# Or for local: ads.set_auth(auth="api_key", oci_config_location="~/.oci/config")

# Configuration
COMPARTMENT_ID = "ocid1.compartment.oc1..xxxxx"
PROJECT_ID = "ocid1.datascienceproject.oc1.iad.xxxxx"

# Create container runtime configuration
container_runtime = ModelDeploymentContainerRuntime()
container_runtime.image = "iad.ocir.io/<tenancy>/vllm-ds:latest"
container_runtime.server_port = 8000
container_runtime.health_check_port = 8000
container_runtime.env = {
    "MODEL_NAME": "meta-llama/Llama-3.1-8B-Instruct",
    # Note: For production, use OCI Vault secrets instead of hardcoding tokens
    "HF_TOKEN": "your-huggingface-token",  # Replace with actual token
    "VLLM_MAX_MODEL_LEN": "4096",
}

# Create deployment
deployment = ModelDeployment(
    display_name="vllm-llama-8b",
    description="vLLM inference for Llama 3.1 8B",
    compartment_id=COMPARTMENT_ID,
    project_id=PROJECT_ID,
)

# Configure compute shape
deployment.infrastructure.shape_name = "VM.GPU.A10.1"
deployment.infrastructure.replica_count = 1
deployment.infrastructure.bandwidth_mbps = 10

# Set container runtime
deployment.runtime = container_runtime

# Deploy
deployment.deploy(wait_for_completion=True)

print(f"Deployment URL: {deployment.url}")
```

## Step 4: Deploy Using OCI CLI

Alternative deployment using OCI CLI:

```bash
# Create model deployment
oci data-science model-deployment create \
    --compartment-id "${OCI_COMPARTMENT_ID}" \
    --project-id "${PROJECT_ID}" \
    --display-name "vllm-llama-8b" \
    --model-deployment-configuration-details "{
        \"deploymentType\": \"SINGLE_MODEL\",
        \"modelConfigurationDetails\": {
            \"modelId\": \"${MODEL_ID}\",
            \"instanceConfiguration\": {
                \"instanceShapeName\": \"VM.GPU.A10.1\"
            },
            \"scalingPolicy\": {
                \"policyType\": \"FIXED_SIZE\",
                \"instanceCount\": 1
            }
        },
        \"environmentConfigurationDetails\": {
            \"environmentConfigurationType\": \"OCIR_CONTAINER\",
            \"image\": \"iad.ocir.io/${TENANCY}/vllm-ds:latest\",
            \"serverPort\": 8000,
            \"healthCheckPort\": 8000,
            \"environmentVariables\": {
                \"MODEL_NAME\": \"meta-llama/Llama-3.1-8B-Instruct\",
                \"HF_TOKEN\": \"${HF_TOKEN}\"
            }
        }
    }"
```

## Step 5: Test the Deployment

Get the deployment endpoint:

```python
# Get endpoint URL
endpoint = deployment.url
print(f"Endpoint: {endpoint}")
```

Send inference request:

```bash
curl -X POST "${ENDPOINT}/v1/completions" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "meta-llama/Llama-3.1-8B-Instruct",
        "prompt": "Hello, how are you?",
        "max_tokens": 50
    }'
```

## Available GPU Shapes for Model Deployment

| Shape | GPUs | GPU Memory | vCPUs | Memory |
|-------|------|------------|-------|--------|
| VM.GPU.A10.1 | 1 | 24 GB | 15 | 240 GB |
| VM.GPU.A10.2 | 2 | 48 GB | 30 | 480 GB |
| BM.GPU.A10.4 | 4 | 96 GB | 64 | 1024 GB |
| BM.GPU4.8 | 8 | 320 GB | 128 | 2048 GB |
| BM.GPU.A100-v2.8 | 8 | 640 GB | 128 | 2048 GB |

## Autoscaling Configuration

Configure autoscaling based on metrics:

```python
deployment.infrastructure.scaling_policy = {
    "policy_type": "AUTOSCALING",
    "auto_scaling_policies": [{
        "auto_scaling_policy_type": "THRESHOLD",
        "initial_instance_count": 1,
        "minimum_instance_count": 1,
        "maximum_instance_count": 5,
        "rules": [{
            "metric_type": "CPU_UTILIZATION",
            "threshold": {
                "duration_in_seconds": 300,
                "operator": "GREATER_THAN",
                "value": 80
            },
            "scale_in_configuration": {
                "instance_count_adjustment": 1,
                "pending_duration_in_seconds": 300
            },
            "scale_out_configuration": {
                "instance_count_adjustment": 1,
                "pending_duration_in_seconds": 300
            }
        }]
    }]
}
```

## Monitoring

View deployment metrics in OCI Console:
- CPU/GPU utilization
- Memory usage
- Request latency
- Request count

Or query metrics via API:

```python
import oci

monitoring_client = oci.monitoring.MonitoringClient(config)
response = monitoring_client.summarize_metrics_data(
    compartment_id=COMPARTMENT_ID,
    summarize_metrics_data_details=oci.monitoring.models.SummarizeMetricsDataDetails(
        namespace="oci_datascience_modeldeploy",
        query="CpuUtilization[1m].mean()",
        start_time=start_time,
        end_time=end_time,
        resolution="1m"
    )
)
```

## Cleanup

Delete the deployment:

```python
deployment.delete(wait_for_completion=True)
```

Or via CLI:

```bash
oci data-science model-deployment delete \
    --model-deployment-id "${DEPLOYMENT_ID}" \
    --force
```

## References

- [OCI Data Science Model Deployment](https://docs.oracle.com/en-us/iaas/data-science/using/model-dep-about.htm)
- [Oracle ADS SDK](https://accelerated-data-science.readthedocs.io/)
- [Bring Your Own Container](https://docs.oracle.com/en-us/iaas/data-science/using/mod-dep-byoc.htm)
