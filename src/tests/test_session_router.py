from typing import Dict

from vllm_router.routers.routing_logic import SessionRouter


class EndpointInfo:
    def __init__(self, url: str):
        self.url = url


class RequestStats:
    def __init__(self, qps: float):
        self.qps = qps


class Request:
    def __init__(self, headers: Dict[str, str]):
        self.headers = headers


# Test cases


def test_route_request_with_session_id():
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
    url = router.route_request(endpoints, None, request_stats, request)

    # Ensure the same session ID always maps to the same endpoint
    assert url == router.route_request(endpoints, None, request_stats, request)


def test_route_request_without_session_id():
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
    url = router.route_request(endpoints, None, request_stats, request)

    # Ensure the endpoint with the lowest QPS is selected
    assert url == "http://engine2.com"


def test_route_request_with_dynamic_endpoints():
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
    url1 = router.route_request(endpoints, None, request_stats, request)

    # Add a new endpoint
    endpoints.append(EndpointInfo(url="http://engine3.com"))
    request_stats["http://engine3.com"] = RequestStats(qps=2)
    url2 = router.route_request(endpoints, None, request_stats, request)

    # Ensure the session ID is still mapped to a valid endpoint
    assert url2 in [endpoint.url for endpoint in endpoints]


def test_consistent_hashing_remove_node_multiple_sessions():
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
        router.route_request(endpoints, None, request_stats, req) for req in requests
    ]

    # Remove an endpoint
    removed_endpoint = endpoints.pop(1)  # Remove http://engine2.com
    del request_stats[removed_endpoint.url]

    # Route with the updated endpoints
    urls_after = [
        router.route_request(endpoints, None, request_stats, req) for req in requests
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


def test_consistent_hashing_add_node_multiple_sessions():
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
        router.route_request(endpoints, None, request_stats, req) for req in requests
    ]

    # Add a new endpoint
    new_endpoint = EndpointInfo(url="http://engine3.com")
    endpoints.append(new_endpoint)
    request_stats[new_endpoint.url] = RequestStats(qps=2)

    # Route with the updated endpoints
    urls_after = [
        router.route_request(endpoints, None, request_stats, req) for req in requests
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


def test_consistent_hashing_add_then_remove_node():
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
        router.route_request(endpoints, None, request_stats, req) for req in requests
    ]

    # Add a new endpoint
    new_endpoint = EndpointInfo(url="http://engine3.com")
    endpoints.append(new_endpoint)
    request_stats[new_endpoint.url] = RequestStats(qps=2)

    # Route with the updated endpoints (after adding)
    urls_after_add = [
        router.route_request(endpoints, None, request_stats, req) for req in requests
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
        router.route_request(endpoints, None, request_stats, req) for req in requests
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
