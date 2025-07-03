import random
from collections import Counter
from unittest.mock import patch

import pytest

from vllm_router.routers.routing_logic import LoadBalancingRouter
from vllm_router.service_discovery import EndpointInfo

try:
    from lmcache.v1.cache_controller import controller_manager
    from lmcache.v1.cache_controller.message import (
        LookupMsg,
        QueryInstMsg,
        QueryInstRetMsg,
    )
except ImportError:
    pass


class MockRequest:
    pass


@pytest.mark.asyncio
async def test_load_balancing_router_balances_across_models():
    router = LoadBalancingRouter(lmcache_controller_port=1234)
    router.start_kv_manager()
    # Define endpoints with various model sizes
    endpoints = [
        EndpointInfo("http://endpoint-small", "llama-7b", 0.0, "small", None, None, 0),
        EndpointInfo(
            "http://endpoint-medium", "mistral-13b", 0.0, "medium", None, None, 0
        ),
        EndpointInfo(
            "http://endpoint-large", "custom-70B", 0.0, "large", None, None, 0
        ),
    ]
    for ep in endpoints:
        router.register_endpoint(ep)

    # Setup tokenization mock (300 tokens)
    token_count = 300
    with patch("requests.post") as mock_post:
        mock_post.return_value.json.return_value = {"tokens": [42] * token_count}

        # No KV cache hits
        router.kv_manager.handle_orchestration_message = lambda msg: type(
            "MockRetMsg", (), {"layout_info": {}}
        )()

        engine_stats = {}
        request_stats = {}
        request_json = {"prompt": "Once upon a time...", "model": "llama-7b"}

        # Simulate 6 sequential requests
        request_results = []
        for i in range(6):
            request = MockRequest()
            selected_url = await router.route_request(
                endpoints, engine_stats, request_stats, request, request_json
            )
            request_results.append(selected_url)

        print("\nRequest Routing Results:")
        for i, url in enumerate(request_results):
            print(f"Request {i+1}: Routed to {url}")

        print("\nFinal Endpoint Loads and Estimated TTFTs:")
        for ep in endpoints:
            stats = router.endpoint_stats[ep.url]
            est_ttft = router.estimate_ttft(token_count, stats.current_load, ep.url)
            print(
                f"{ep.url:<12} | Load: {stats.current_load} | TTFT: {est_ttft:.6f} | URL: {ep.url}"
            )

        # Assert that no endpoint has more than 3 requests and all endpoints are used
        endpoint_usage = {ep.url: request_results.count(ep.url) for ep in endpoints}
        assert all(1 <= count <= 3 for count in endpoint_usage.values())
        assert len(set(request_results)) >= 2  # At least 2 different endpoints used


@pytest.mark.asyncio
async def test_router_balances_many_requests():
    router = LoadBalancingRouter(lmcache_controller_port=1234)
    router.start_kv_manager()

    # Register endpoints with different models
    endpoints = [
        EndpointInfo("http://endpoint-small", "llama-7b", 0.0, "small", None, None, 0),
        EndpointInfo(
            "http://endpoint-medium", "mistral-13b", 0.0, "medium", None, None, 0
        ),
        EndpointInfo(
            "http://endpoint-large", "custom-70B", 0.0, "large", None, None, 0
        ),
    ]
    for ep in endpoints:
        router.register_endpoint(ep)

    # Patch KV cache logic to simulate zero cache hits
    router.kv_manager.handle_orchestration_message = lambda msg: type(
        "MockRetMsg", (), {"layout_info": {}}
    )()

    engine_stats = {}
    request_stats = {}

    routing_results = []

    with patch("requests.post") as mock_post:
        num_requests = 30
        for i in range(num_requests):
            req = MockRequest()
            # Randomly pick a prompt size: small (30), medium (100), large (800)
            prompt_len = random.choice([30, 100, 800])
            mock_post.return_value.json.return_value = {"tokens": [42] * prompt_len}
            request_json = {"prompt": "X" * prompt_len, "model": "llama-7b"}

            selected_url = await router.route_request(
                endpoints, engine_stats, request_stats, req, request_json
            )
            routing_results.append((prompt_len, selected_url))

            # Simulate request load tracking
            router.endpoint_stats[selected_url].current_load += 1
            # Optionally, simulate that load goes down again
            router.endpoint_stats[selected_url].current_load = max(
                0, router.endpoint_stats[selected_url].current_load - 1
            )

    # Count number of times each endpoint was chosen
    usage_counts = Counter(url for _, url in routing_results)

    print("\nRouting Distribution Summary:")
    for ep in endpoints:
        print(f"{ep.url:<25}: {usage_counts[ep.url]} selections")

    # Assert all endpoints were used at least once
    assert all(usage_counts[ep.url] > 0 for ep in endpoints)

    # Assert no single endpoint dominates (>70% usage)
    max_allowed = int(num_requests * 0.7)
    assert all(count <= max_allowed for count in usage_counts.values())

    # Print breakdown by prompt size
    print("\nBreakdown by Prompt Size:")
    size_buckets = {30: "small", 100: "medium", 800: "large"}
    for prompt_len, url in routing_results:
        print(f"{size_buckets[prompt_len]:>6} prompt → {url}")


@pytest.mark.asyncio
async def test_load_balancing_with_request_completion():
    router = LoadBalancingRouter(lmcache_controller_port=1234)
    router.start_kv_manager()

    # Register endpoints
    endpoints = [
        EndpointInfo("http://endpoint-small", "llama-7b", 0.0, "small", None, None, 0),
        EndpointInfo(
            "http://endpoint-medium", "mistral-13b", 0.0, "medium", None, None, 0
        ),
        EndpointInfo(
            "http://endpoint-large", "custom-70B", 0.0, "large", None, None, 0
        ),
    ]
    for ep in endpoints:
        router.register_endpoint(ep)

    # Patch tokenizer response (300 tokens = medium prompt)
    token_count = 300
    with patch("requests.post") as mock_post:
        mock_post.return_value.json.return_value = {"tokens": [42] * token_count}

        # Patch KV cache (no hits)
        router.kv_manager.handle_orchestration_message = lambda msg: type(
            "MockRetMsg", (), {"layout_info": {}}
        )()

        engine_stats = {}
        request_stats = {}
        request_json = {
            "prompt": "Explain the theory of relativity",
            "model": "llama-7b",
        }

        selected_endpoints = []

        # Step 1: Send 3 initial requests to fill up load
        for _ in range(3):
            request = MockRequest()
            selected = await router.route_request(
                endpoints, engine_stats, request_stats, request, request_json
            )
            selected_endpoints.append(selected)
            # Simulate dispatch: increase load
            router.endpoint_stats[selected].current_load += 1

        # Step 2: Randomly choose 2 endpoints to simulate completion
        for _ in range(2):
            candidate = random.choice(endpoints).url
            stats = router.endpoint_stats[candidate]
            if stats.current_load > 0:
                router.complete_request(candidate)

        # Step 3: Send 3 more requests
        for _ in range(3):
            request = MockRequest()
            selected = await router.route_request(
                endpoints, engine_stats, request_stats, request, request_json
            )
            selected_endpoints.append(selected)
            router.endpoint_stats[selected].current_load += 1

        print("\nRouting Decisions:")
        for i, url in enumerate(selected_endpoints):
            print(f"Request {i+1}: {url}")

        print("\nFinal Load State:")
        for ep in endpoints:
            stats = router.endpoint_stats[ep.url]
            print(f"{ep.url:<25} | Load: {stats.current_load}")

        # Assert all endpoints were used at least once
        endpoint_usage = {ep.url: selected_endpoints.count(ep.url) for ep in endpoints}
        assert all(count > 0 for count in endpoint_usage.values())
