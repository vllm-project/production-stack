from typing import Any, Dict

import pytest

from vllm_router.routers import routing_logic
from vllm_router.routers.routing_logic import SessionRouter, cleanup_routing_logic


class EndpointInfo:
    def __init__(self, url: str):
        self.url = url


class RequestStats:
    def __init__(self, qps: float):
        self.qps = qps


class Request:
    def __init__(self, headers: Dict[str, str], body: Dict[str, Any] = None):
        self.headers = headers
        self.body = body


# Test cases


@pytest.mark.asyncio
async def test_route_request_with_session_id():
    """
    Test routing when a session ID is present in the request headers.
    """
    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
    ]
    request_stats = {
        "http://engine1.com": RequestStats(qps=10),
        "http://engine2.com": RequestStats(qps=5),
    }
    request = Request(headers={"session_id": "abc123"})

    router = SessionRouter(session_key="session_id")
    url = await router.route_request(endpoints, None, request_stats, request, {})

    # Ensure the same session ID always maps to the same endpoint
    assert url == await router.route_request(
        endpoints, None, request_stats, request, {}
    )


@pytest.mark.asyncio
async def test_route_request_without_session_id():
    """
    Test routing when no session ID is present in the request headers.
    """
    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
    ]
    request_stats = {
        "http://engine1.com": RequestStats(qps=10),
        "http://engine2.com": RequestStats(qps=5),
    }
    request = Request(headers={})  # No session ID

    router = SessionRouter(session_key="session_id")
    url = await router.route_request(endpoints, None, request_stats, request, {})

    # Ensure the endpoint with the lowest QPS is selected
    assert url == "http://engine2.com"


@pytest.mark.asyncio
async def test_route_request_with_dynamic_endpoints():
    """
    Test routing when the list of endpoints changes dynamically.
    """
    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
    ]
    request_stats = {
        "http://engine1.com": RequestStats(qps=10),
        "http://engine2.com": RequestStats(qps=5),
    }
    request = Request(headers={"session_id": "abc123"})

    router = SessionRouter(session_key="session_id")
    await router.route_request(endpoints, None, request_stats, request, {})

    # Add a new endpoint
    endpoints.append(EndpointInfo(url="http://engine3.com"))
    request_stats["http://engine3.com"] = RequestStats(qps=2)
    url2 = await router.route_request(endpoints, None, request_stats, request, {})

    # Ensure the session ID is still mapped to a valid endpoint
    assert url2 in [endpoint.url for endpoint in endpoints]


@pytest.mark.asyncio
async def test_consistent_hashing_remove_node_multiple_sessions():
    """
    Test consistent hashing behavior with multiple session IDs when a node is removed.
    """
    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
        EndpointInfo(url="http://engine3.com"),
    ]
    request_stats = {
        "http://engine1.com": RequestStats(qps=10),
        "http://engine2.com": RequestStats(qps=5),
        "http://engine3.com": RequestStats(qps=2),
    }
    session_ids = ["session1", "session2", "session3", "session4", "session5"]
    requests = [Request(headers={"session_id": sid}) for sid in session_ids]

    router = SessionRouter(session_key="session_id")

    # Route with initial endpoints
    urls_before = [
        await router.route_request(endpoints, None, request_stats, req, {})
        for req in requests
    ]

    # Remove an endpoint
    removed_endpoint = endpoints.pop(1)  # Remove http://engine2.com
    del request_stats[removed_endpoint.url]

    # Route with the updated endpoints
    urls_after = [
        await router.route_request(endpoints, None, request_stats, req, {})
        for req in requests
    ]

    # Ensure all session IDs are still mapped to valid endpoints
    assert all(url in [endpoint.url for endpoint in endpoints] for url in urls_after)

    # Calculate the number of remapped session IDs
    remapped_count = sum(
        1 for before, after in zip(urls_before, urls_after) if before != after
    )

    # Ensure minimal reassignment
    # Only a fraction should be remapped
    assert remapped_count < len(session_ids)


@pytest.mark.asyncio
async def test_consistent_hashing_add_node_multiple_sessions():
    """
    Test consistent hashing behavior with multiple session IDs when a node is added.
    """
    # Initial endpoints
    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
    ]
    request_stats = {
        "http://engine1.com": RequestStats(qps=10),
        "http://engine2.com": RequestStats(qps=5),
    }
    session_ids = ["session1", "session2", "session3", "session4", "session5"]
    requests = [Request(headers={"session_id": sid}) for sid in session_ids]

    router = SessionRouter(session_key="session_id")

    # Route with initial endpoints
    urls_before = [
        await router.route_request(endpoints, None, request_stats, req, {})
        for req in requests
    ]

    # Add a new endpoint
    new_endpoint = EndpointInfo(url="http://engine3.com")
    endpoints.append(new_endpoint)
    request_stats[new_endpoint.url] = RequestStats(qps=2)

    # Route with the updated endpoints
    urls_after = [
        await router.route_request(endpoints, None, request_stats, req, {})
        for req in requests
    ]

    # Ensure all session IDs are still mapped to valid endpoints
    assert all(url in [endpoint.url for endpoint in endpoints] for url in urls_after)

    # Calculate the number of remapped session IDs
    remapped_count = sum(
        1 for before, after in zip(urls_before, urls_after) if before != after
    )

    # Ensure minimal reassignment
    # Only a fraction should be remapped
    assert remapped_count < len(session_ids)


@pytest.mark.asyncio
async def test_consistent_hashing_add_then_remove_node():
    """
    Test consistent hashing behavior when a node is added and then removed.
    """
    # Initial endpoints
    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
    ]
    request_stats = {
        "http://engine1.com": RequestStats(qps=10),
        "http://engine2.com": RequestStats(qps=5),
    }
    session_ids = ["session1", "session2", "session3", "session4", "session5"]
    requests = [Request(headers={"session_id": sid}) for sid in session_ids]

    router = SessionRouter(session_key="session_id")

    # Route with initial endpoints
    urls_before_add = [
        await router.route_request(endpoints, None, request_stats, req, {})
        for req in requests
    ]

    # Add a new endpoint
    new_endpoint = EndpointInfo(url="http://engine3.com")
    endpoints.append(new_endpoint)
    request_stats[new_endpoint.url] = RequestStats(qps=2)

    # Route with the updated endpoints (after adding)
    urls_after_add = [
        await router.route_request(endpoints, None, request_stats, req, {})
        for req in requests
    ]

    # Ensure all session IDs are still mapped to valid endpoints
    assert all(
        url in [endpoint.url for endpoint in endpoints] for url in urls_after_add
    )

    # Calculate the number of remapped session IDs after adding
    remapped_count_after_add = sum(
        1 for before, after in zip(urls_before_add, urls_after_add) if before != after
    )

    # Ensure minimal reassignment after adding
    assert remapped_count_after_add < len(session_ids)

    # Remove the added endpoint
    removed_endpoint = endpoints.pop()  # Remove http://engine3.com
    del request_stats[removed_endpoint.url]

    # Route with the updated endpoints (after removing)
    urls_after_remove = [
        await router.route_request(endpoints, None, request_stats, req, {})
        for req in requests
    ]

    # Ensure all session IDs are still mapped to valid endpoints
    assert all(
        url in [endpoint.url for endpoint in endpoints] for url in urls_after_remove
    )

    # Calculate the number of remapped session IDs after removing
    remapped_count_after_remove = sum(
        1 for before, after in zip(urls_after_add, urls_after_remove) if before != after
    )

    # Ensure minimal reassignment after removing
    assert remapped_count_after_remove < len(session_ids)

    # Verify that session IDs mapped to unaffected nodes remain the same
    unaffected_count = sum(
        1
        for before, after in zip(urls_before_add, urls_after_remove)
        if before == after
    )
    print(
        f"{unaffected_count} out of {len(session_ids)} session IDs were unaffected by adding and removing a node."
    )


@pytest.mark.asyncio
async def test_session_key_in_request_body():
    """
    Test routing when a session ID is present in the request body.
    """
    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
    ]
    request_stats = {
        "http://engine1.com": RequestStats(qps=10),
        "http://engine2.com": RequestStats(qps=5),
    }
    request = Request(headers={}, body={"session_id": "abc123"})
    router = SessionRouter(session_key="session_id")
    url = await router.route_request(
        endpoints, None, request_stats, request, request.body
    )
    assert url == "http://engine1.com"
    assert router.extract_session_id(request, request.body) == "abc123"
    url2 = await router.route_request(
        endpoints, None, request_stats, request, request.body
    )
    assert url2 == "http://engine1.com"


MODEL_A = [EndpointInfo(url=f"http://a{i}.com") for i in range(8)]
MODEL_B = [EndpointInfo(url=f"http://b{i}.com") for i in range(8)]
SESSION_IDS = [f"session{i}" for i in range(20)]


@pytest.fixture
def fresh_router():
    cleanup_routing_logic()
    yield SessionRouter(session_key="session_id")
    cleanup_routing_logic()


@pytest.fixture
def ring_builds(monkeypatch):
    builds = []

    class CountingHashRing(routing_logic.HashRing):
        def __init__(self, nodes=None, **kwargs):
            builds.append(frozenset(nodes or ()))
            super().__init__(nodes, **kwargs)

    monkeypatch.setattr(routing_logic, "HashRing", CountingHashRing)
    return builds


async def route_session(router, endpoints, session_id):
    request = Request(headers={"session_id": session_id})
    return await router.route_request(endpoints, None, {}, request, {})


@pytest.mark.asyncio
async def test_alternating_models_build_each_ring_once(fresh_router, ring_builds):
    for sid in SESSION_IDS:
        await route_session(fresh_router, MODEL_A, sid)
        await route_session(fresh_router, MODEL_B, sid)

    assert sorted(map(len, ring_builds)) == [8, 8]


@pytest.mark.asyncio
async def test_alternating_models_route_like_single_model(fresh_router):
    single = [await route_session(fresh_router, MODEL_A, sid) for sid in SESSION_IDS]

    cleanup_routing_logic()
    router = SessionRouter(session_key="session_id")
    alternating = []
    for sid in SESSION_IDS:
        alternating.append(await route_session(router, MODEL_A, sid))
        await route_session(router, MODEL_B, sid)

    assert alternating == single


@pytest.mark.asyncio
async def test_no_session_id_builds_no_ring(fresh_router, ring_builds):
    request = Request(headers={})
    url = await fresh_router.route_request(MODEL_A, None, {}, request, {})

    assert url in [e.url for e in MODEL_A]
    assert ring_builds == []


@pytest.mark.asyncio
async def test_ring_cache_clear_keeps_session_placement(fresh_router):
    before = [await route_session(fresh_router, MODEL_A, sid) for sid in SESSION_IDS]

    for i in range(routing_logic.RoutingInterface._MAX_CACHE_SIZE + 1):
        await route_session(fresh_router, [EndpointInfo(url=f"http://x{i}.com")], "s")

    after = [await route_session(fresh_router, MODEL_A, sid) for sid in SESSION_IDS]
    assert after == before
