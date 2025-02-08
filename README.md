# vLLM Production Stack: reference stack for production vLLM deployment

## Latest News

- ✨ Join us at #production-stack channel of vLLM [slack](https://slack.vllm.ai/), LMCache [slack](https://join.slack.com/t/lmcacheworkspace/shared_invite/zt-2viziwhue-5Amprc9k5hcIdXT7XevTaQ), or fill out this [interest form](https://forms.gle/wSoeNpncmPVdXppg8) for a chat!
- 🛤️ 2025 Q1 Road Map Released! Join the discussion [here](https://github.com/vllm-project/production-stack/issues/26)!
- 🔥 vLLM Production Stack is released! Checkout our [release blogs](https://blog.lmcache.ai/2025-01-21-stack-release) [01-22-2025]

## Introduction

**vLLM Production Stack** project provides a reference implementation on how to build an inference stack on top of vLLM, which allows you to:

- 🚀 Scale from single vLLM instance to distributed vLLM deployment without changing any application code
- 💻 Monitor the  through a web dashboard
- 😄 Enjoy the performance benefits brought by request routing and KV cache offloading

## Step-By-Step Tutorials

0. How To [*Install Kubernetes (kubectl, helm, minikube, etc)*](https://github.com/vllm-project/production-stack/blob/main/tutorials/00-install-kubernetes-env.md)?
1. How To [*Setup a Minimal vLLM Production Stack*](https://github.com/vllm-project/production-stack/blob/main/tutorials/01-minimal-helm-installation.md)?
2. How To [*Customize vLLM Configs (optional)*](https://github.com/vllm-project/production-stack/blob/main/tutorials/02-basic-vllm-config.md)?
3. How to [*Load Your LLM Weights*](https://github.com/vllm-project/production-stack/blob/main/tutorials/03-load-model-from-pv.md)?
4. How to [*Launch Different LLMs in vLLM Production Stack*](https://github.com/vllm-project/production-stack/blob/main/tutorials/04-launch-multiple-model.md)?
5. How to [*Enable KV Cache Offloading with LMCache*](https://github.com/vllm-project/production-stack/blob/main/tutorials/05-offload-kv-cache.md)?

## Architecture

The stack is set up using [Helm](https://helm.sh/docs/), and contains the following key parts:

- **Serving engine**: The vLLM engines that run different LLMs
- **Request router**: Directs requests to appropriate backends based on routing keys or session IDs to maximize KV cache reuse.
- **Observability stack**: monitors the metrics of the backends through [Prometheus](https://github.com/prometheus/prometheus) + [Grafana](https://grafana.com/)

<p align="center">
  <img src="https://github.com/user-attachments/assets/8f05e7b9-0513-40a9-9ba9-2d3acca77c0c" alt="Architecture of the stack" width="80%"/>
</p>

## Roadmap

We are actively working on this project and will release the following features soon. Please stay tuned!

- **Autoscaling** based on vLLM-specific metrics
- Support for **disaggregated prefill**
- **Router improvements** (e.g., more performant router using non-python languages, KV-cache-aware routing algorithm, better fault tolerance, etc)

## Deploying the stack via Helm

### Prerequisites

- A running Kubernetes (K8s) environment with GPUs
  - Run `cd utils && bash install-minikube-cluster.sh`
  - Or follow our [tutorial](tutorials/00-install-kubernetes-env.md)

### Deployment

vLLM Production Stack can be deployed via helm charts. Clone the repo to local and execute the following commands for a minimal deployment:

```bash
git clone https://github.com/vllm-project/production-stack.git
cd production-stack/
helm repo add vllm https://vllm-project.github.io/production-stack
helm install vllm vllm/vllm-stack -f tutorials/assets/values-01-minimal-example.yaml
```

The deployed stack provides the same [**OpenAI API interface**](https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html?ref=blog.mozilla.ai#openai-compatible-server) as vLLM, and can be accessed through kubernetes service.

To validate the installation and and send query to the stack, refer to [this tutorial](tutorials/01-minimal-helm-installation.md).

For more information about customizing the helm chart, please refer to [values.yaml](https://github.com/vllm-project/production-stack/blob/main/helm/values.yaml) and our other [tutorials](https://github.com/vllm-project/production-stack/tree/main/tutorials).

### Uninstall

```bash
sudo helm uninstall vllm
```

## Grafana Dashboard

### Features

The Grafana dashboard provides the following insights:

1. **Available vLLM Instances**: Displays the number of healthy instances.
2. **Request Latency Distribution**: Visualizes end-to-end request latency.
3. **Time-to-First-Token (TTFT) Distribution**: Monitors response times for token generation.
4. **Number of Running Requests**: Tracks the number of active requests per instance.
5. **Number of Pending Requests**: Tracks requests waiting to be processed.
6. **GPU KV Usage Percent**: Monitors GPU KV cache usage.
7. **GPU KV Cache Hit Rate**: Displays the hit rate for the GPU KV cache.

<p align="center">
  <img src="https://github.com/user-attachments/assets/05766673-c449-4094-bdc8-dea6ac28cb79" alt="Grafana dashboard to monitor the deployment" width="80%"/>
</p>

### Configuration

See the details in [`observability/README.md`](./observability/README.md)

## Router

The router ensures efficient request distribution among backends. It supports:

- Routing to endpoints that run different models
- Exporting observability metrics for each serving engine instance, including QPS, time-to-first-token (TTFT), number of pending/running/finished requests, and uptime
- Automatic service discovery and fault tolerance by Kubernetes API
- Multiple different routing algorithms
  - Round-robin routing
  - Session-ID based routing
  - (WIP) prefix-aware routing

Please refer to the [router documentation](./router/README.md) for more details.

## Contributing

Contributions are welcome! Please follow the standard GitHub flow:

1. Fork the repository.
2. Create a feature branch.
3. Submit a pull request with detailed descriptions.

### Formatting

We use `pre-commit` for formatting, it is installed as follows:

```bash
pip install -r requirements-lint.txt
pre-commit install
```

It will run automatically before every commit. You can also run it manually on
all files with:

```bash
pre-commit run --all-files
```

There are a subset of hooks which require additional dependencies that you may
not have installed in your development environment (i.e. Docker and non-Python
packages). These are configured to only run in the `manual` `pre-commit` stage.
In CI they are run in the `pre-commit-manual` job, and locally they can be run
with:

```bash
# Runs all hooks including manual stage hooks
pre-commit run --all-files --hook-stage manual
# Runs only the manual stage hook shellcheck
pre-commit run --all-files --hook-stage manual shellcheck
```

If any of these hooks are failing in CI but you cannot run them locally, you
can identify what needs changing by examining the GitHub Actions logs in your
pull request.

> You can read more about `pre-commit` at <https://pre-commit.com>.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.

---

For any issues or questions, feel free to open an issue or contact the maintainers.
