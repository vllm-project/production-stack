#!/usr/bin/env python3
"""
OCI Data Science Model Deployment for vLLM

This script deploys a vLLM inference endpoint using OCI Data Science
Model Deployment service with custom container support.

Usage:
    python deploy_model.py --compartment-id <COMPARTMENT_OCID> --project-id <PROJECT_OCID>

Environment variables:
    OCI_COMPARTMENT_ID: OCI compartment OCID
    OCI_PROJECT_ID: Data Science project OCID
    HF_TOKEN: Hugging Face token for model download
    OCIR_IMAGE: Container image URL in OCIR
"""

import argparse
import os
import sys

try:
    import ads
    from ads.model.deployment import (
        ModelDeployment,
        ModelDeploymentContainerRuntime,
        ModelDeploymentInfrastructure,
    )
except ImportError:
    print("Error: oracle-ads package not installed.")
    print("Install with: pip install oracle-ads")
    sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Deploy vLLM model using OCI Data Science"
    )
    parser.add_argument(
        "--compartment-id",
        default=os.environ.get("OCI_COMPARTMENT_ID"),
        help="OCI compartment OCID",
    )
    parser.add_argument(
        "--project-id",
        default=os.environ.get("OCI_PROJECT_ID"),
        help="Data Science project OCID",
    )
    parser.add_argument(
        "--display-name",
        default="vllm-inference",
        help="Deployment display name",
    )
    parser.add_argument(
        "--model-name",
        default="meta-llama/Llama-3.1-8B-Instruct",
        help="Hugging Face model name",
    )
    parser.add_argument(
        "--shape",
        default="VM.GPU.A10.1",
        choices=[
            "VM.GPU.A10.1",
            "VM.GPU.A10.2",
            "BM.GPU.A10.4",
            "BM.GPU4.8",
            "BM.GPU.A100-v2.8",
        ],
        help="GPU compute shape",
    )
    parser.add_argument(
        "--replica-count",
        type=int,
        default=1,
        help="Number of replicas",
    )
    parser.add_argument(
        "--image",
        default=os.environ.get("OCIR_IMAGE", "vllm/vllm-openai:latest"),
        help="Container image URL",
    )
    parser.add_argument(
        "--max-model-len",
        type=int,
        default=4096,
        help="Maximum model context length",
    )
    parser.add_argument(
        "--gpu-memory-utilization",
        type=float,
        default=0.90,
        help="GPU memory utilization (0.0-1.0)",
    )
    parser.add_argument(
        "--auth",
        choices=["api_key", "resource_principal", "instance_principal"],
        default="api_key",
        help="Authentication method",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete existing deployment with same name",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        default=True,
        help="Wait for deployment to complete",
    )

    return parser.parse_args()


def setup_auth(auth_method: str):
    """Configure OCI authentication."""
    if auth_method == "api_key":
        ads.set_auth(auth="api_key", oci_config_location="~/.oci/config")
    elif auth_method == "resource_principal":
        ads.set_auth(auth="resource_principal")
    elif auth_method == "instance_principal":
        ads.set_auth(auth="instance_principal")


def get_existing_deployment(compartment_id: str, display_name: str):
    """Find existing deployment by name."""
    deployments = ModelDeployment.list(compartment_id=compartment_id)
    for dep in deployments:
        if dep.display_name == display_name:
            return dep
    return None


def create_deployment(args) -> ModelDeployment:
    """Create and configure model deployment."""

    # Get HuggingFace token
    hf_token = os.environ.get("HF_TOKEN", "")
    if not hf_token and "llama" in args.model_name.lower():
        print("Warning: HF_TOKEN not set. Llama models require authentication.")

    # Configure container runtime
    container_runtime = ModelDeploymentContainerRuntime()
    container_runtime.image = args.image
    container_runtime.server_port = 8000
    container_runtime.health_check_port = 8000
    container_runtime.env = {
        "MODEL_NAME": args.model_name,
        "VLLM_MAX_MODEL_LEN": str(args.max_model_len),
        "VLLM_GPU_MEMORY_UTILIZATION": str(args.gpu_memory_utilization),
    }

    if hf_token:
        container_runtime.env["HF_TOKEN"] = hf_token
        container_runtime.env["HUGGING_FACE_HUB_TOKEN"] = hf_token

    # Configure infrastructure
    infrastructure = ModelDeploymentInfrastructure()
    infrastructure.shape_name = args.shape
    infrastructure.replica_count = args.replica_count
    infrastructure.bandwidth_mbps = 10

    # Create deployment
    deployment = ModelDeployment(
        display_name=args.display_name,
        description=f"vLLM inference deployment for {args.model_name}",
        compartment_id=args.compartment_id,
        project_id=args.project_id,
    )

    deployment.runtime = container_runtime
    deployment.infrastructure = infrastructure

    return deployment


def main():
    args = parse_args()

    # Validate required arguments
    if not args.compartment_id:
        print("Error: --compartment-id or OCI_COMPARTMENT_ID is required")
        sys.exit(1)

    if not args.project_id:
        print("Error: --project-id or OCI_PROJECT_ID is required")
        sys.exit(1)

    # Setup authentication
    print(f"Setting up authentication: {args.auth}")
    setup_auth(args.auth)

    # Check for existing deployment
    if args.delete:
        existing = get_existing_deployment(args.compartment_id, args.display_name)
        if existing:
            print(f"Deleting existing deployment: {existing.id}")
            existing.delete(wait_for_completion=True)
            print("Existing deployment deleted.")

    # Create new deployment
    print(f"Creating deployment: {args.display_name}")
    print(f"  Model: {args.model_name}")
    print(f"  Shape: {args.shape}")
    print(f"  Replicas: {args.replica_count}")
    print(f"  Image: {args.image}")

    deployment = create_deployment(args)

    # Deploy
    print("\nStarting deployment...")
    deployment.deploy(wait_for_completion=args.wait)

    if args.wait:
        print("\nDeployment completed!")
        print(f"  Deployment ID: {deployment.id}")
        print(f"  Endpoint URL: {deployment.url}")
        print("\nTest with:")
        print(f'  curl -X POST "{deployment.url}/v1/completions" \\')
        print('    -H "Content-Type: application/json" \\')
        print("    -d '{")
        print(f'      "model": "{args.model_name}",')
        print('      "prompt": "Hello, how are you?",')
        print('      "max_tokens": 50')
        print("    }'")
    else:
        print("\nDeployment started in background.")
        print(f"  Deployment ID: {deployment.id}")
        print("\nCheck status with:")
        print(f"  oci data-science model-deployment get --model-deployment-id {deployment.id}")


if __name__ == "__main__":
    main()
