.PHONY: precommit precommit_hadolint precommit_helmlint precommit_shellcheck precommit_checkov
.PHONY: functionality_secure functionality_twopods functionality_multiple
.PHONY: router_e2e router_k8s_discovery router_static_discovery python_tests operator_crd_test

all: python_tests precommit precommit_hadolint precommit_helmlint precommit_shellcheck precommit_checkov router_e2e router_k8s_discovery router_static_discovery functionality_secure functionality_twopods functionality_multiple operator_crd_test


# 1. Python Tests - CI Python tests (from ci.yml)
python_tests:
	pip install uv
	uv sync --all-extras --all-groups
	uv run pytest
	echo "✅ Python tests completed!"

# 2. Pre-commit - General pre-commit checks (from pre-commit.yml)
precommit:
	pip install ruff
	ruff check src
	echo "✅ Pre-commit checks completed!"

# 3. Pre-commit manual: hadolint-docker - Docker linting
precommit_hadolint:
	pre-commit run --all-files -v --hook-stage manual hadolint-docker; \
	echo "✅ Hadolint-docker checks completed!"

# 4. Pre-commit manual: helmlint - Helm chart linting
precommit_helmlint:
	pre-commit run --all-files -v --hook-stage manual helmlint; \
	echo "✅ Helmlint checks completed!"

# 5. Pre-commit manual: shellcheck - Shell script linting
precommit_shellcheck:
	pre-commit run --all-files -v --hook-stage manual shellcheck; \
	echo "✅ Shellcheck checks completed!"

# 6. Pre-commit manual: checkov - Security scanning
precommit_checkov:
	pre-commit run --all-files -v --hook-stage manual checkov; \
	echo "✅ Checkov security checks completed!"


# 7. Router E2E tests: e2e-test - Basic E2E test (from router-e2e-test.yml)
router_e2e:
	@set -eu; \
	echo "🔧 Ensuring port 8000 is free"; \
	if command -v lsof >/dev/null 2>&1 && lsof -i :8000 -t >/dev/null 2>&1; then \
		lsof -i :8000 -t | xargs -r kill -9 || true; \
		sleep 2; \
	fi; \
	python -m pip install --upgrade pip; \
	pip install -r src/tests/requirements.txt; \
	pip install -r requirements-test.txt; \
	pip install -e .; \
	chmod +x src/vllm_router/perf-test.sh; \
	chmod +x src/tests/perftest/*.sh; \
	( cd src/tests/perftest && bash run-multi-server.sh 4 500 ); \
	sleep 10; \
	bash src/vllm_router/perf-test.sh 8000 & \
	sleep 5; \
	mkdir -p src/tests/perftest/logs; \
	PYTHONPATH=$$(pwd) python3 -v src/tests/perftest/request_generator.py --qps 10 --num-workers 32 --duration 300 2>&1 | tee src/tests/perftest/logs/request_generator.log; \
	pip install coverage; \
	coverage run --source=src/vllm_router -m pytest src/tests/test_*.py; \
	coverage report -m > coverage.txt; \
	( cd src/tests/perftest && bash clean-up.sh ) || echo "Cleanup failed"; \
	echo "✅ Router E2E tests completed!"

# 8. Router E2E tests: k8s-discovery-e2e-test - Kubernetes discovery test (from router-e2e-test.yml)
router_k8s_discovery:
	@set -eu; \
	echo "🔍 Running Kubernetes discovery E2E tests..."; \
	echo "⚠️  This test requires a running Kubernetes cluster (minikube)"; \
	\
	# Ensure required CLI tools exist
	for cmd in minikube kubectl docker; do \
		if ! command -v $$cmd >/dev/null 2>&1; then \
			echo "❌ Missing required command: $$cmd"; \
			exit 1; \
		fi; \
	done; \
	\
	# Optional: activate conda env if your machine has the same setup as CI
	if [ -f /usr/local/bin/conda-init ]; then \
		echo "📦 Activating conda environment 'llmstack'"; \
		. /usr/local/bin/conda-init || true; \
		conda activate llmstack || true; \
	fi; \
	\
	echo "📦 Installing dependencies..."; \
	python -m pip install --upgrade pip || true; \
	pip install -r benchmarks/multi-round-qa/requirements.txt || echo "ℹ️ benchmarks requirements not found, continuing"; \
	pip install -e .; \
	\
	echo "🔧 Setting up minikube environment..."; \
	if ! minikube status >/dev/null 2>&1; then \
		echo "❌ Minikube not running. Please start minikube first."; \
		exit 1; \
	fi; \
	kubectl config use-context minikube; \
	\
	echo "🔨 Building router Docker image in minikube's daemon..."; \
	eval "$$(minikube docker-env)"; \
	DOCKER_BUILDKIT=1 docker build --build-arg INSTALL_OPTIONAL_DEP=default -t git-act-router -f docker/Dockerfile.kvaware .; \
	\
	echo "🧪 Running k8s discovery routing tests..."; \
	chmod +x tests/e2e/run-k8s-routing-test.sh; \
	RESULTS_DIR="$${RESULTS_DIR:-/tmp/k8s-discovery-routing-results}"; \
	./tests/e2e/run-k8s-routing-test.sh all \
		--model "facebook/opt-125m" \
		--num-requests 25 \
		--chunk-size 128 \
		--verbose \
		--result-dir "$$RESULTS_DIR" \
		--timeout 10; \
	\
	echo "✅ Kubernetes discovery E2E tests completed!"

# 9. Router E2E tests: static-discovery-e2e-test - Static discovery test (from router-e2e-test.yml)
router_static_discovery:
	@set -eu; \
	echo "🔍 Running Static discovery E2E tests..."; \
	\
	# Optional conda activation (mirrors CI if available)
	if [ -f /usr/local/bin/conda-init ]; then \
		echo "📦 Activating conda environment 'llmstack'"; \
		. /usr/local/bin/conda-init || true; \
		conda activate llmstack || true; \
	fi; \
	\
	echo "📦 Installing dependencies..."; \
	python -m pip install --upgrade pip || true; \
	pip install -e .; \
	pip install vllm lmcache || echo "⚠️ vLLM/lmcache installation failed, continuing..."; \
	\
	LOG_DIR="/tmp/static-discovery-e2e-test"; \
	mkdir -p "$$LOG_DIR"; \
	\
	echo "🚀 Starting vLLM serve backends..."; \
	echo "Starting backend 1 on port 8001..."; \
	CUDA_VISIBLE_DEVICES=0 vllm serve facebook/opt-125m --port 8001 --gpu-memory-utilization 0.7 --chat-template .github/template-chatml.jinja > "$$LOG_DIR/backend1.log" 2>&1 & \
	echo "Starting backend 2 on port 8002..."; \
	CUDA_VISIBLE_DEVICES=1 vllm serve facebook/opt-125m --port 8002 --gpu-memory-utilization 0.7 --chat-template .github/template-chatml.jinja > "$$LOG_DIR/backend2.log" 2>&1 & \
	\
	echo "⏳ Waiting for backends to be ready..."; \
	chmod +x tests/e2e/wait-for-backends.sh; \
	./tests/e2e/wait-for-backends.sh 180 "http://localhost:8001" "http://localhost:8002"; \
	\
	echo "🧪 Running static discovery routing tests..."; \
	chmod +x tests/e2e/run-static-discovery-routing-test.sh; \
	./tests/e2e/run-static-discovery-routing-test.sh all \
		--pythonpath "$$PYTHONPATH" \
		--log-dir "$$LOG_DIR" \
		--num-requests 20 \
		--verbose \
		--backends-url "http://localhost:8001,http://localhost:8002"; \
	\
	echo "🧹 Cleaning up processes..."; \
	pkill -f "vllm serve" || true; \
	pkill -f "python3 -m src.vllm_router.app" || true; \
	\
	echo "✅ Static discovery E2E tests completed!"

# 10. Functionality test: Secure-Minimal-Example - Helm chart functionality test (from functionality-helm-chart.yml)
functionality_secure:
	@set -eu; \
	echo "🔍 Running Secure Minimal Example functionality test..."; \
	echo "⚠️  Requires a running Kubernetes cluster (minikube), Helm, and Docker"; \
	\
	# Check required tools
	for cmd in helm kubectl docker minikube timeout; do \
		if ! command -v $$cmd >/dev/null 2>&1; then \
			echo "❌ Missing required command: $$cmd"; \
			exit 1; \
		fi; \
	done; \
	\
	# Ensure minikube is running and context is set
	if ! minikube status >/dev/null 2>&1; then \
		echo "❌ Minikube not running. Please start minikube first."; \
		exit 1; \
	fi; \
	kubectl config use-context minikube; \
	\
	# Cleanup on exit/failure
	trap 'echo \"🧹 Cleaning up...\"; helm uninstall vllm >/dev/null 2>&1 || true; sudo docker image prune -f >/dev/null 2>&1 || true; echo \"✅ Cleanup done\"' EXIT; \
	\
	echo "🧼 Uninstalling any existing helm releases (current namespace)..."; \
	releases=$$(helm list -q); \
	if [ -n "$$releases" ]; then \
		for r in $$releases; do echo \" - uninstall $$r\"; helm uninstall "$$r" || true; done; \
	else \
		echo " (none)"; \
	fi; \
	\
	echo "⏳ Waiting for pods to terminate..."; \
	# wait until no pods are listed; ignores errors when no pods exist
	COUNT=0; \
	while kubectl get pods --no-headers 2>/dev/null | grep -q .; do \
		COUNT=$$((COUNT+1)); \
		if [ $$COUNT -gt 60 ]; then echo \"Timed out waiting for pods\"; break; fi; \
		sleep 5; \
	done; \
	\
	echo "🛠️  Building Docker image (docker/Dockerfile)"; \
	sudo docker build --build-arg INSTALL_OPTIONAL_DEP=default -t localhost:5000/git-act-router -f docker/Dockerfile .; \
	echo "📤 Pushing image to local registry localhost:5000"; \
	sudo docker push localhost:5000/git-act-router; \
	\
	echo "🔧 Adjusting kernel flag (fs.protected_regular=0)"; \
	sudo sysctl fs.protected_regular=0 || true; \
	\
	echo "📦 Loading image into minikube"; \
	minikube image load localhost:5000/git-act-router; \
	\
	echo "🚀 Deploying via Helm chart with secure values"; \
	helm install vllm ./helm -f .github/values-05-secure-vllm.yaml; \
	\
	echo "🧪 Validating installation (port-forward + curl)"; \
	if ! timeout 180 bash .github/port-forward.sh curl-05-secure-vllm; then \
		echo "❌ Validation failed"; \
	fi; \
	\
	echo "✅ Secure Minimal Example functionality test completed!"

# 11. Functionality test: Two-Pods-Minimal-Example - Two pods test (from functionality-helm-chart.yml)
functionality_twopods:
	@set -eu; \
	echo "🔍 Running Two Pods Minimal Example functionality test..."; \
	echo "⚠️  Requires a running Kubernetes cluster (minikube) and Helm"; \
	\
	# Check required tools
	for cmd in helm kubectl minikube timeout; do \
		if ! command -v $$cmd >/dev/null 2>&1; then \
			echo "❌ Missing required command: $$cmd"; \
			exit 1; \
		fi; \
	done; \
	\
	# Ensure minikube is running and set context
	if ! minikube status >/dev/null 2>&1; then \
		echo "❌ Minikube not running. Please start minikube first."; \
		exit 1; \
	fi; \
	kubectl config use-context minikube; \
	\
	# Cleanup on exit
	trap 'echo \"🧹 Cleaning up...\"; helm uninstall vllm >/dev/null 2>&1 || true; echo \"✅ Cleanup done\"' EXIT; \
	\
	echo "🧼 Uninstalling any existing helm releases (current namespace)..."; \
	releases=$$(helm list -q); \
	if [ -n "$$releases" ]; then \
		for r in $$releases; do echo \" - uninstall $$r\"; helm uninstall "$$r" || true; done; \
	else \
		echo " (none)"; \
	fi; \
	\
	echo "⏳ Waiting for pods to terminate..."; \
	COUNT=0; \
	while kubectl get pods --no-headers 2>/dev/null | grep -q .; do \
		COUNT=$$((COUNT+1)); \
		if [ $$COUNT -gt 60 ]; then echo \"Timed out waiting for pods\"; break; fi; \
		sleep 5; \
	done; \
	\
	echo "🚀 Deploying Helm chart (two pods minimal example)..."; \
	helm install vllm ./helm -f .github/values-01-2pods-minimal-example.yaml; \
	\
	echo "🧪 Validating installation (port-forward + curl)"; \
	if ! timeout 180 bash .github/port-forward.sh curl-02-two-pods; then \
		echo "❌ Validation failed"; \
	fi; \
	\
	echo "✅ Two Pods Minimal Example functionality test completed!"


# 12. Functionality test: Multiple-Models - Multiple models test (from functionality-helm-chart.yml)
functionality_multiple:
	@set -eu; \
	echo "🔍 Running Multiple Models functionality test..."; \
	echo "⚠️  Requires a running Kubernetes cluster (minikube) and Helm"; \
	\
	# Check required tools
	for cmd in helm kubectl minikube timeout; do \
		if ! command -v $$cmd >/dev/null 2>&1; then \
			echo "❌ Missing required command: $$cmd"; \
			exit 1; \
		fi; \
	done; \
	\
	# Ensure minikube is running and set context
	if ! minikube status >/dev/null 2>&1; then \
		echo "❌ Minikube not running. Please start minikube first."; \
		exit 1; \
	fi; \
	kubectl config use-context minikube; \
	\
	# Cleanup on exit (always try to uninstall the release)
	trap 'echo "🧹 Cleaning up..."; helm uninstall vllm >/dev/null 2>&1 || true; echo "✅ Cleanup done"' EXIT; \
	\
	echo "🧼 Uninstalling any existing helm releases (current namespace)..."; \
	releases=$$(helm list -q); \
	if [ -n "$$releases" ]; then \
		for r in $$releases; do echo " - uninstall $$r"; helm uninstall "$$r" || true; done; \
	else \
		echo " (none)"; \
	fi; \
	\
	echo "⏳ Waiting for pods to terminate..."; \
	COUNT=0; \
	while kubectl get pods --no-headers 2>/dev/null | grep -q .; do \
		COUNT=$$((COUNT+1)); \
		if [ $$COUNT -gt 60 ]; then echo "Timed out waiting for pods"; break; fi; \
		sleep 5; \
	done; \
	\
	echo "🚀 Deploying Helm chart (multiple models)"; \
	helm install vllm ./helm -f .github/values-04-multiple-models.yaml; \
	\
	echo "🧪 Validating installation (port-forward + curl)"; \
	if ! timeout 300 bash .github/port-forward.sh curl-04-multiple-models; then \
		echo "❌ Validation failed"; \
	fi; \
	\
	echo "✅ Multiple Models functionality test completed!"


# 13. Operator CRD and CR Testing - CRD-Validation test (from operator-test.yml)
operator_crd_test:
	@set -eu; \
	echo "🔍 Running Operator CRD and CR Testing..."; \
	echo "⚠️  Requires a running Kubernetes cluster (minikube)"; \
	\
	# Check required tools
	for cmd in kubectl minikube; do \
		if ! command -v $$cmd >/dev/null 2>&1; then \
			echo "❌ Missing required command: $$cmd"; \
			exit 1; \
		fi; \
	done; \
	\
	echo "🔧 Setting up test environment..."; \
	sudo sysctl fs.protected_regular=0 || true; \
	if ! minikube status >/dev/null 2>&1; then \
		echo "❌ Minikube not running. Please start minikube first."; \
		exit 1; \
	fi; \
	kubectl config use-context minikube; \
	\
	# Always try to clean up CRs/CRDs on exit
	trap 'echo "🧹 Cleaning up test resources..."; \
		kubectl delete vllmruntime --all >/dev/null 2>&1 || true; \
		kubectl delete cacheserver --all >/dev/null 2>&1 || true; \
		kubectl delete vllmrouter --all >/dev/null 2>&1 || true; \
		kubectl delete crd vllmruntimes.production-stack.vllm.ai >/dev/null 2>&1 || true; \
		kubectl delete crd cacheservers.production-stack.vllm.ai >/dev/null 2>&1 || true; \
		kubectl delete crd vllmrouters.production-stack.vllm.ai >/dev/null 2>&1 || true; \
		echo "✅ Cleanup done";' EXIT; \
	\
	echo "📋 Cluster nodes:"; \
	minikube kubectl -- get nodes; \
	\
	echo "🧪 Testing CRDs and CRs..."; \
	chmod +x tests/e2e/test-crds.sh; \
	./tests/e2e/test-crds.sh; \
	\
	echo "✅ Operator CRD and CR Testing completed!"
