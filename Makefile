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
	@echo "🔍 Running Kubernetes discovery E2E tests..."
	@echo "⚠️  This test requires a running Kubernetes cluster (minikube)"
	@echo "Installing dependencies..."
	@pip install -r benchmarks/multi-round-qa/requirements.txt || echo "benchmarks requirements not found"
	@pip install -e .
	@echo "Setting up minikube environment..."
	@minikube status || (echo "❌ Minikube not running. Please start minikube first." && exit 1)
	@kubectl config use-context minikube
	@echo "Building router image..."
	@eval "$$(minikube docker-env)" && docker build --build-arg INSTALL_OPTIONAL_DEP=default -t git-act-router -f docker/Dockerfile.kvaware .
	@echo "Running k8s discovery routing tests..."
	@chmod +x tests/e2e/run-k8s-routing-test.sh
	@./tests/e2e/run-k8s-routing-test.sh all --model "facebook/opt-125m" --num-requests 25 --chunk-size 128 --verbose --result-dir /tmp/k8s-discovery-routing-results --timeout 10
	@echo "✅ Kubernetes discovery E2E tests completed!"

# 9. Router E2E tests: static-discovery-e2e-test - Static discovery test (from router-e2e-test.yml)
router_static_discovery:
	@echo "🔍 Running Static discovery E2E tests..."
	@echo "Installing dependencies..."
	@pip install -e .
	@pip install vllm lmcache || echo "vLLM/lmcache installation failed"
	@echo "Starting vLLM serve backends..."
	@mkdir -p /tmp/static-discovery-e2e-test
	@echo "Starting backend 1 on port 8001..."
	@CUDA_VISIBLE_DEVICES=0 vllm serve facebook/opt-125m --port 8001 --gpu-memory-utilization 0.7 --chat-template .github/template-chatml.jinja > /tmp/static-discovery-e2e-test/backend1.log 2>&1 &
	@echo "Starting backend 2 on port 8002..."
	@CUDA_VISIBLE_DEVICES=1 vllm serve facebook/opt-125m --port 8002 --gpu-memory-utilization 0.7 --chat-template .github/template-chatml.jinja > /tmp/static-discovery-e2e-test/backend2.log 2>&1 &
	@echo "Waiting for backends to be ready..."
	@chmod +x tests/e2e/wait-for-backends.sh
	@./tests/e2e/wait-for-backends.sh 180 "http://localhost:8001" "http://localhost:8002"
	@echo "Running static discovery routing tests..."
	@chmod +x tests/e2e/run-static-discovery-routing-test.sh
	@./tests/e2e/run-static-discovery-routing-test.sh all --log-dir /tmp/static-discovery-e2e-test --num-requests 20 --verbose --backends-url "http://localhost:8001,http://localhost:8002"
	@echo "Cleaning up processes..."
	@pkill -f "vllm serve" || true
	@pkill -f "python3 -m src.vllm_router.app" || true
	@echo "✅ Static discovery E2E tests completed!"

# 10. Functionality test: Secure-Minimal-Example - Helm chart functionality test (from functionality-helm-chart.yml)
functionality_secure:
	@echo "🔍 Running Secure Minimal Example functionality test..."
	@echo "⚠️  This test requires a running Kubernetes cluster (minikube) and Docker"
	@echo "Uninstalling any existing helm releases..."
	@releases=$$(helm list -q); if [ -n "$$releases" ]; then for r in $$releases; do helm uninstall "$$r"; done; fi
	@echo "Waiting for pods to terminate..."
	@while kubectl get pods --no-headers 2>/dev/null | grep -q .; do sleep 5; done
	@echo "Building and pushing Docker image..."
	@kubectl config use-context minikube
	@sudo docker build --build-arg INSTALL_OPTIONAL_DEP=default -t localhost:5000/git-act-router -f docker/Dockerfile .
	@sudo docker push localhost:5000/git-act-router
	@sudo sysctl fs.protected_regular=0
	@minikube image load localhost:5000/git-act-router
	@echo "Deploying via helm charts..."
	@helm install vllm ./helm -f .github/values-05-secure-vllm.yaml
	@echo "Validating installation..."
	@timeout 180 bash .github/port-forward.sh curl-05-secure-vllm || echo "Validation failed"
	@echo "Cleaning up..."
	@helm uninstall vllm || true
	@sudo docker image prune -f || true
	@echo "✅ Secure Minimal Example functionality test completed!"

# 11. Functionality test: Two-Pods-Minimal-Example - Two pods test (from functionality-helm-chart.yml)
functionality_twopods:
	@echo "🔍 Running Two Pods Minimal Example functionality test..."
	@echo "⚠️  This test requires a running Kubernetes cluster (minikube)"
	@echo "Uninstalling any existing helm releases..."
	@releases=$$(helm list -q); if [ -n "$$releases" ]; then for r in $$releases; do helm uninstall "$$r"; done; fi
	@echo "Waiting for pods to terminate..."
	@while kubectl get pods --no-headers 2>/dev/null | grep -q .; do sleep 5; done
	@echo "Deploying via helm charts..."
	@helm install vllm ./helm -f .github/values-01-2pods-minimal-example.yaml
	@echo "Validating installation..."
	@timeout 180 bash .github/port-forward.sh curl-02-two-pods || echo "Validation failed"
	@echo "Cleaning up..."
	@helm uninstall vllm || true
	@echo "✅ Two Pods Minimal Example functionality test completed!"

# 12. Functionality test: Multiple-Models - Multiple models test (from functionality-helm-chart.yml)
functionality_multiple:
	@echo "🔍 Running Multiple Models functionality test..."
	@echo "⚠️  This test requires a running Kubernetes cluster (minikube)"
	@echo "Uninstalling any existing helm releases..."
	@releases=$$(helm list -q); if [ -n "$$releases" ]; then for r in $$releases; do helm uninstall "$$r"; done; fi
	@echo "Waiting for pods to terminate..."
	@while kubectl get pods --no-headers 2>/dev/null | grep -q .; do sleep 5; done
	@echo "Deploying via helm charts..."
	@helm install vllm ./helm -f .github/values-04-multiple-models.yaml
	@echo "Validating installation..."
	@timeout 300 bash .github/port-forward.sh curl-04-multiple-models || echo "Validation failed"
	@echo "Cleaning up..."
	@helm uninstall vllm || true
	@echo "✅ Multiple Models functionality test completed!"

# 13. Operator CRD and CR Testing - CRD-Validation test (from operator-test.yml)
operator_crd_test:
	@echo "🔍 Running Operator CRD and CR Testing..."
	@echo "⚠️  This test requires a running Kubernetes cluster (minikube)"
	@echo "Setting up test environment..."
	@sudo sysctl fs.protected_regular=0 || true
	@minikube status || (echo "❌ Minikube not running. Please start minikube first." && exit 1)
	@minikube kubectl -- get nodes
	@echo "Testing CRDs and CRs..."
	@chmod +x tests/e2e/test-crds.sh
	@./tests/e2e/test-crds.sh
	@echo "Cleaning up test resources..."
	@kubectl delete vllmruntime --all || true
	@kubectl delete cacheserver --all || true
	@kubectl delete vllmrouter --all || true
	@kubectl delete crd vllmruntimes.production-stack.vllm.ai || true
	@kubectl delete crd cacheservers.production-stack.vllm.ai || true
	@kubectl delete crd vllmrouters.production-stack.vllm.ai || true
	@echo "✅ Operator CRD and CR Testing completed!"
