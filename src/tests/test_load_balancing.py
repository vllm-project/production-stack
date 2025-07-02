import pytest
from unittest.mock import AsyncMock, patch

from vllm_router.routers.routing_logic import LoadBalancingRouter
from vllm_router.service_discovery import EndpointInfo
from vllm_router.stats.engine_stats import EngineStats
from vllm_router.stats.request_stats import RequestStats

class MockRequest:
    pass

@pytest.mark.asyncio
async def test_load_balancing_router_balances_across_models():
    router = LoadBalancingRouter(lmcache_controller_port=1234)

    # Define endpoints with various model sizes
    endpoints = [
        EndpointInfo("http://endpoint-small", "llama-7b", 0.0, "small", None, None, 0),
        EndpointInfo("http://endpoint-medium", "mistral-13b", 0.0, "medium", None, None, 0),
        EndpointInfo("http://endpoint-large", "custom-70B", 0.0, "large", None, None, 0),
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
            selected_url = await router.route_request(endpoints, engine_stats, request_stats, request, request_json)
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