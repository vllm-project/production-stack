# vLLM Production Stack - Agent Notes

## Project Structure

Multi-component project for deploying vLLM on Kubernetes:

- `src/vllm_router/` - Python request router (FastAPI)
- `operator/` - Go Kubernetes operator
- `helm/` - Helm chart for K8s deployment
- `src/gateway_inference_extension/` - Gateway API inference extension
- `src/tests/` - Router unit tests and performance tests
- `tests/e2e/` - End-to-end test scripts

## Development Setup

Uses `uv` for Python package management (Python 3.12+):

```bash
uv sync --all-extras --all-groups
uv run pre-commit install
```

## Commands

### Python/Router

```bash
uv run pytest                                    # Run unit tests
uv run pre-commit run --all-files               # Run all pre-commit hooks
uv run pre-commit run --all-files --hook-stage manual  # Include manual hooks (hadolint, helmlint, shellcheck, checkov)
ruff check src                                   # Lint src/tests/ only (ruff configured for this path)
```

Install router locally:

```bash
pip install -e .                      # Basic install
pip install -e .[semantic_cache]      # With semantic cache support
pip install -e .[lmcache]             # With LMCache support
```

Build router Docker image:

```bash
docker build -t <name>:<tag> -f docker/Dockerfile .
```

### Go Operator (from `operator/` directory)

```bash
make build          # Build manager binary
make test           # Run unit tests (requires envtest setup)
make test-e2e       # Run e2e tests (requires running Kind cluster)
make lint           # Run golangci-lint
make deploy         # Deploy to current K8s context
```

### Helm (from `helm/` directory)

```bash
helm dependency build
helm install llmstack . -f values-example.yaml
helm uninstall llmstack
```

## CI/CD Notes

- E2E tests run on self-hosted runners with GPUs/minikube
- Router E2E tests start mock OpenAI servers and vLLM backends
- Pre-commit manual-stage hooks run in CI via `pre-commit-manual` job

## PR Conventions

Prefix PR titles with: `[Bugfix]`, `[CI/Build]`, `[Doc]`, `[Feat]`, `[Router]`, `[Misc]`

DCO required: use `git commit -s` to add `Signed-off-by`.

## Architecture Notes

- Router entrypoint: `src/vllm_router/app.py:main` (installed as `vllm-router` CLI)
- Router supports two service discovery modes: `k8s` and `static`
- Routing logic options: `roundrobin`, `session`, `prefixaware`, `kvaware`
- Operator uses kubebuilder scaffolding; CRDs in `operator/config/crd/bases/`
