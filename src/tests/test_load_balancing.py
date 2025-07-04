import pytest
from unittest.mock import patch, AsyncMock
import random
from vllm_router.routers.routing_logic import LoadBalancingRouter
from vllm_router.service_discovery import EndpointInfo


class MockRequest:
    pass

@pytest.mark.asyncio
async def test_simple_load_balancing_routing():
    router = LoadBalancingRouter(lmcache_controller_port=1234)

    # Register 3 mock endpoints
    endpoints = [
        EndpointInfo("http://endpoint-small", "llama-7b", 0.0, "small", None, None, 0),
        EndpointInfo("http://endpoint-medium", "mistral-13b", 0.0, "medium", None, None, 0),
        EndpointInfo("http://endpoint-large", "custom-70B", 0.0, "large", None, None, 0),
    ]
    for ep in endpoints:
        router.register_endpoint(ep)

    # Patch tokenizer to return 300 tokens
    with patch("transformers.AutoTokenizer.from_pretrained") as mock_tokenizer_class:
        mock_tokenizer = mock_tokenizer_class.return_value
        mock_tokenizer.encode.return_value = [42] * 300  # medium prompt

        # Patch cache lookup: no hits (simulate miss)
        router.kv_manager.handle_orchestration_message = AsyncMock()
        router.kv_manager.handle_orchestration_message.return_value = type(
            "MockInstanceID", (), {"layout_info": {}}
        )()

        engine_stats = {}
        request_stats = {}
        request_json = {"prompt": "What is the capital of France?", "model": "llama-7b"}

        request = MockRequest()
        selected_url = await router.route_request(
            endpoints, engine_stats, request_stats, request, request_json
        )

        print(f"\nSelected URL: {selected_url}")
        assert selected_url in [ep.url for ep in endpoints]
        assert router.endpoint_stats[selected_url].current_load == 1

@pytest.mark.asyncio
async def test_balancing_under_load():
    router = LoadBalancingRouter(lmcache_controller_port=1234)

    # Register endpoints of different model sizes
    endpoints = [
        EndpointInfo("http://endpoint-small", "llama-7b", 0.0, "small", None, None, 0),
        EndpointInfo("http://endpoint-medium", "mistral-13b", 0.0, "medium", None, None, 0),
        EndpointInfo("http://endpoint-large", "custom-70B", 0.0, "large", None, None, 0),
    ]
    for ep in endpoints:
        router.register_endpoint(ep)

    # Patch tokenizer
    with patch("transformers.AutoTokenizer.from_pretrained") as mock_tokenizer_class:
        mock_tokenizer = mock_tokenizer_class.return_value

        # Patch KV cache: no hits
        router.kv_manager.handle_orchestration_message = AsyncMock()
        router.kv_manager.handle_orchestration_message.return_value = type(
            "MockInstanceID", (), {"layout_info": {}}
        )()

        engine_stats = {}
        request_stats = {}

        prompts = [
            ("short prompt", 100),     # small
            ("medium prompt", 300),    # medium
            ("long prompt", 900),      # large
        ]

        routing_results = []

        for _ in range(20):  # simulate 20 requests
            prompt_text, size = random.choice(prompts)
            mock_tokenizer.encode.return_value = [42] * size

            request_json = {"prompt": prompt_text, "model": "llama-7b"}
            request = MockRequest()

            selected_url = await router.route_request(
                endpoints, engine_stats, request_stats, request, request_json
            )
            routing_results.append(selected_url)

        # Print endpoint usage
        endpoint_usage = {ep.url: routing_results.count(ep.url) for ep in endpoints}
        print("\nRouting Distribution:")
        for url, count in endpoint_usage.items():
            print(f"{url}: {count} requests")

        # Assert at least 2 endpoints were used
        assert len([url for url, count in endpoint_usage.items() if count > 0]) >= 2