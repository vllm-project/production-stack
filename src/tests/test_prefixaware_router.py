import asyncio
from typing import Dict

from vllm_router.routers.routing_logic import PrefixAwareRouter


class EndpointInfo:
    def __init__(self, url: str):
        self.url = url


class RequestStats:
    def __init__(self, qps: float):
        self.qps = qps


class Request:
    def __init__(self, headers: Dict[str, str]):
        self.headers = headers


class EngineStats:
    def __init__(self):
        return


def test_prefixaware_logic():
    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
    ]
    request_stats = {
        "http://engine1.com": RequestStats(qps=10),
        "http://engine2.com": RequestStats(qps=5),
    }
    request = Request(headers={})

    router = PrefixAwareRouter()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        request_json = {"prompt": "Hello, how are you today?"}
        url = loop.run_until_complete(
            router.route_request(endpoints, None, request_stats, request, request_json)
        )
        assert url in [endpoint.url for endpoint in endpoints]

        # Same request should route to same endpoint
        url2 = loop.run_until_complete(
            router.route_request(endpoints, None, request_stats, request, request_json)
        )
        assert url == url2, "Same request should route to same endpoint"

        # chat messages should work
        chat_request = {
            "messages": [{"role": "user", "content": "Hello, how are you?"}]
        }
        url3 = loop.run_until_complete(
            router.route_request(endpoints, None, request_stats, request, chat_request)
        )
        assert url3 in [endpoint.url for endpoint in endpoints]

    finally:
        loop.close()


def test_hashtrie_eviction():
    from vllm_router.prefix.config import HashTrieConfig
    from vllm_router.prefix.hashtrie import HashTrie

    # Create a config with very small memory limit to trigger eviction
    config = HashTrieConfig.from_defaults(
        chunk_size=4,  # Small chunk size
        max_memory_size=0.0,  # 0 MB - should trigger immediate eviction
        eviction_threshold=0.5,
        target_utilization=0.0,  # evict all of the nodes
        memory_check_request_batch_size=5,
    )

    # Create a new HashTrie with the restrictive config
    hashtrie = HashTrie(config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # Insert a request - this should trigger eviction due to 0 MB limit
        request = "Hello world, this is a test request"
        endpoint = "http://engine1.com"

        # Before insertion
        initial_size = len(hashtrie.node_cache)
        assert initial_size == 0, "HashTrie should start empty"

        # Insert a couple of times to trigger the memory check and cache eviction
        for i in range(config.memory_check_request_batch_size):
            loop.run_until_complete(hashtrie.insert(request, endpoint))

        # After insertion with 0 MB limit, eviction should have occurred
        # The trie might be empty or have very few nodes due to aggressive eviction
        final_size = len(hashtrie.node_cache)

        # With 0 MB limit, the eviction should keep the trie very small
        assert (
            final_size == 0
        ), f"HashTrie should be small after eviction, got {final_size} nodes"

    finally:
        loop.close()
