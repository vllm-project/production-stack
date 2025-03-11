# Benchmarking vLLM Production Stack Router Overhead

## Overview

This directory contains benchmarking scripts for evaluation vLLM Production Stack's router overhead (e.g., latency).

## Setup

Installing the required packages needed to run the benchmark by:

```bash
pip install openai
```

## Running benchmarks

```bash
python3 test-router.py \
    --model meta-llama/Llama-3.1-8B-Instruct \
    --base-url http://localhost:30080/v1
```

This script requires there is a serving engine with the  `meta-llama/Llama-3.1-8B-Instruct` model served locally at ``http://localhost:30080/v1``.

Here's an example command to launch the serving engine with vLLM Production Stack:

```bash
helm repo add vllm https://vllm-project.github.io/production-stack
helm install vllm vllm/vllm-stack -f model.yaml
```

And then do port-forwarding with the following command:

```bash
sudo kubectl port-forward svc/vllm-router-service 30080:80
```
