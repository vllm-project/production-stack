import time
from unittest.mock import MagicMock, patch

import pytest

from vllm_router.routers.disaggregated_qoe_router import DisaggregatedQoERouter
from vllm_router.service_discovery import EndpointInfo
from vllm_router.stats.engine_stats import EngineStats
from vllm_router.stats.request_stats import RequestStats


class MockRequest:
    def __init__(self, headers=None, json_data=None, request_id=None):
        self.headers = headers or {}
        self.scope = {"json": json_data} if json_data else {}
        if request_id:
            self.scope["request_id"] = request_id


def test_router_initialization():
    """Test that the DisaggregatedQoERouter initializes correctly with default and custom parameters"""
    # Test default initialization
    router = DisaggregatedQoERouter()
    assert router.prefill_tag == "prefill"
    assert router.decoding_tag == "decoding"
    assert router.priority_header == "x-request-priority"

    # Test custom initialization
    custom_router = DisaggregatedQoERouter(
        prefill_tag="pf", decoding_tag="dc", priority_header="custom-priority"
    )
    assert custom_router.prefill_tag == "pf"
    assert custom_router.decoding_tag == "dc"
    assert custom_router.priority_header == "custom-priority"


def test_filter_endpoints_by_tag():
    """Test filtering endpoints by tag"""
    router = DisaggregatedQoERouter()

    # Create test endpoints
    endpoints = [
        EndpointInfo(url="http://vllm-prefill-1.com"),
        EndpointInfo(url="http://vllm-decoding-1.com"),
        EndpointInfo(url="http://vllm-general-1.com"),
    ]

    # Test filtering for prefill endpoints
    prefill_endpoints = router._filter_endpoints_by_tag(endpoints, "prefill")
    assert len(prefill_endpoints) == 1
    assert prefill_endpoints[0].url == "http://vllm-prefill-1.com"

    # Test filtering for decoding endpoints
    decoding_endpoints = router._filter_endpoints_by_tag(endpoints, "decoding")
    assert len(decoding_endpoints) == 1
    assert decoding_endpoints[0].url == "http://vllm-decoding-1.com"


def test_is_prefill_request():
    """Test the logic to determine if a request is in prefill phase"""
    router = DisaggregatedQoERouter()

    # Test with empty messages (should be prefill)
    request = MockRequest(json_data={"messages": []})
    assert router._is_prefill_request(request) is True

    # Test with only user messages (should be prefill)
    request = MockRequest(
        json_data={"messages": [{"role": "user", "content": "Hello"}]}
    )
    assert router._is_prefill_request(request) is True

    # Test with assistant messages (should be decoding)
    request = MockRequest(
        json_data={
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there"},
            ]
        }
    )
    assert router._is_prefill_request(request) is False

    # Test with parent_id (should be decoding)
    request = MockRequest(json_data={"parent_id": "123", "messages": []})
    assert router._is_prefill_request(request) is False


def test_extract_request_id():
    """Test extracting request ID"""
    router = DisaggregatedQoERouter()

    # Test with request ID in headers
    request = MockRequest(headers={"x-request-id": "abc123"})
    assert router._extract_request_id(request) == "abc123"

    # Test with request ID in scope
    request = MockRequest()
    request.scope["request_id"] = "def456"
    assert router._extract_request_id(request) == "def456"

    # Test with no request ID (should generate one)
    request = MockRequest()
    request_id = router._extract_request_id(request)
    assert request_id.startswith("req_")


def test_calculate_prefill_score():
    """Test calculation of prefill scores"""
    router = DisaggregatedQoERouter()

    # Create test data
    url = "http://vllm-prefill-1.com"
    engine_stats = {
        url: EngineStats(
            num_running_requests=5,
            num_queuing_requests=2,
            gpu_prefix_cache_hit_rate=0.8,
            gpu_cache_usage_perc=0.5,
        )
    }
    request_stats = {
        url: RequestStats(
            qps=10.0,
            ttft=0.2,  # 200ms TTFT (good)
            in_prefill_requests=3,
            in_decoding_requests=0,
            finished_requests=100,
            uptime=3600,
            avg_decoding_length=0.0,
            avg_latency=2.0,
            avg_itl=0.0,
            num_swapped_requests=0,
        )
    }

    # Calculate score
    score = router._calculate_prefill_score(url, engine_stats, request_stats)

    # Score should be between 0 and 1
    assert 0 <= score <= 1

    # Create another endpoint with worse TTFT
    url2 = "http://vllm-prefill-2.com"
    engine_stats[url2] = EngineStats(
        num_running_requests=5,
        num_queuing_requests=2,
        gpu_prefix_cache_hit_rate=0.5,  # Worse cache hit rate
        gpu_cache_usage_perc=0.5,
    )
    request_stats[url2] = RequestStats(
        qps=10.0,
        ttft=0.4,  # 400ms TTFT (worse)
        in_prefill_requests=3,
        in_decoding_requests=0,
        finished_requests=100,
        uptime=3600,
        avg_decoding_length=0.0,
        avg_latency=2.0,
        avg_itl=0.0,
        num_swapped_requests=0,
    )

    # Calculate scores
    score1 = router._calculate_prefill_score(url, engine_stats, request_stats)
    score2 = router._calculate_prefill_score(url2, engine_stats, request_stats)

    # The better endpoint should have a lower score
    assert score1 < score2


def test_calculate_decoding_score():
    """Test calculation of decoding scores"""
    router = DisaggregatedQoERouter()

    # Create test data
    url = "http://vllm-decoding-1.com"
    engine_stats = {
        url: EngineStats(
            num_running_requests=5,
            num_queuing_requests=2,
            gpu_prefix_cache_hit_rate=0.5,
            gpu_cache_usage_perc=0.5,
        )
    }
    request_stats = {
        url: RequestStats(
            qps=10.0,
            ttft=0.3,
            in_prefill_requests=0,
            in_decoding_requests=5,
            finished_requests=100,
            uptime=3600,
            avg_decoding_length=10.0,
            avg_latency=2.0,
            avg_itl=0.02,  # 20ms ITL (good)
            num_swapped_requests=0,
        )
    }

    # Calculate score
    score = router._calculate_decoding_score(url, engine_stats, request_stats, 500)

    # Score should be between 0 and 1
    assert 0 <= score <= 1

    # Create another endpoint with worse ITL
    url2 = "http://vllm-decoding-2.com"
    engine_stats[url2] = EngineStats(
        num_running_requests=5,
        num_queuing_requests=2,
        gpu_prefix_cache_hit_rate=0.5,
        gpu_cache_usage_perc=0.5,
    )
    request_stats[url2] = RequestStats(
        qps=10.0,
        ttft=0.3,
        in_prefill_requests=0,
        in_decoding_requests=5,
        finished_requests=100,
        uptime=3600,
        avg_decoding_length=10.0,
        avg_latency=2.0,
        avg_itl=0.05,  # 50ms ITL (worse)
        num_swapped_requests=0,
    )

    # Calculate scores
    score1 = router._calculate_decoding_score(url, engine_stats, request_stats, 500)
    score2 = router._calculate_decoding_score(url2, engine_stats, request_stats, 500)

    # The better endpoint should have a lower score
    assert score1 < score2

    # Test that longer expected output affects the score calculation
    score3 = router._calculate_decoding_score(url, engine_stats, request_stats, 2000)
    # Long output should be factored differently
    assert score3 != score1


def test_route_prefill_request():
    """Test routing prefill requests"""
    router = DisaggregatedQoERouter()

    # Create test endpoints
    prefill_endpoints = [
        EndpointInfo(url="http://vllm-prefill-1.com"),
        EndpointInfo(url="http://vllm-prefill-2.com"),
    ]

    # Create engine stats
    engine_stats = {
        "http://vllm-prefill-1.com": EngineStats(
            num_running_requests=5,
            num_queuing_requests=1,
            gpu_prefix_cache_hit_rate=0.8,
            gpu_cache_usage_perc=0.5,
        ),
        "http://vllm-prefill-2.com": EngineStats(
            num_running_requests=3,
            num_queuing_requests=0,
            gpu_prefix_cache_hit_rate=0.7,
            gpu_cache_usage_perc=0.4,
        ),
    }

    # Create request stats (second endpoint has better TTFT)
    request_stats = {
        "http://vllm-prefill-1.com": RequestStats(
            qps=10.0,
            ttft=0.25,
            in_prefill_requests=5,
            in_decoding_requests=0,
            finished_requests=100,
            uptime=3600,
            avg_decoding_length=0.0,
            avg_latency=2.0,
            avg_itl=0.0,
            num_swapped_requests=0,
        ),
        "http://vllm-prefill-2.com": RequestStats(
            qps=8.0,
            ttft=0.15,  # Better TTFT
            in_prefill_requests=3,
            in_decoding_requests=0,
            finished_requests=80,
            uptime=3600,
            avg_decoding_length=0.0,
            avg_latency=1.8,
            avg_itl=0.0,
            num_swapped_requests=0,
        ),
    }

    # Test routing
    request = MockRequest(
        headers={"x-request-priority": "1"},
        json_data={"messages": [{"role": "user", "content": "Hello"}]},
    )
    request_id = "test-req-1"
    url = router.route_prefill_request(
        prefill_endpoints, engine_stats, request_stats, request, request_id, 1.0
    )

    # Should choose the endpoint with better TTFT
    assert url == "http://vllm-prefill-2.com"

    # Check tracking data
    assert request_id in router.request_tracking
    assert "prefill_start_time" in router.request_tracking[request_id]
    assert (
        router.request_tracking[request_id]["prefill_endpoint"]
        == "http://vllm-prefill-2.com"
    )


def test_route_decoding_request():
    """Test routing decoding requests"""
    router = DisaggregatedQoERouter()

    # Create test endpoints
    decoding_endpoints = [
        EndpointInfo(url="http://vllm-decoding-1.com"),
        EndpointInfo(url="http://vllm-decoding-2.com"),
    ]

    # Create engine stats
    engine_stats = {
        "http://vllm-decoding-1.com": EngineStats(
            num_running_requests=5,
            num_queuing_requests=2,
            gpu_prefix_cache_hit_rate=0.5,
            gpu_cache_usage_perc=0.6,
        ),
        "http://vllm-decoding-2.com": EngineStats(
            num_running_requests=8,
            num_queuing_requests=1,
            gpu_prefix_cache_hit_rate=0.4,
            gpu_cache_usage_perc=0.7,
        ),
    }

    # Create request stats (second endpoint has better ITL)
    request_stats = {
        "http://vllm-decoding-1.com": RequestStats(
            qps=15.0,
            ttft=0.3,
            in_prefill_requests=0,
            in_decoding_requests=5,
            finished_requests=150,
            uptime=3600,
            avg_decoding_length=8.0,
            avg_latency=2.5,
            avg_itl=0.04,
            num_swapped_requests=0,
        ),
        "http://vllm-decoding-2.com": RequestStats(
            qps=12.0,
            ttft=0.35,
            in_prefill_requests=0,
            in_decoding_requests=8,
            finished_requests=120,
            uptime=3600,
            avg_decoding_length=10.0,
            avg_latency=2.8,
            avg_itl=0.02,  # Better ITL
            num_swapped_requests=0,
        ),
    }

    # Setup request tracking with existing prefill data
    request_id = "test-req-2"
    router.request_tracking[request_id] = {
        "prefill_start_time": time.time() - 0.3,  # 300ms ago
        "prefill_endpoint": "http://vllm-prefill-1.com",
        "priority": 1.0,
    }

    # Test routing
    request = MockRequest(
        headers={"x-request-priority": "1", "x-expected-output-tokens": "1000"},
        json_data={
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there"},
            ]
        },
    )
    url = router.route_decoding_request(
        decoding_endpoints, engine_stats, request_stats, request, request_id, 1.0, 1000
    )

    # Should choose the endpoint with better ITL
    assert url == "http://vllm-decoding-2.com"

    # Check updated tracking data
    assert "decoding_start_time" in router.request_tracking[request_id]
    assert (
        router.request_tracking[request_id]["decoding_endpoint"]
        == "http://vllm-decoding-2.com"
    )


def test_route_request_prefill_phase():
    """Test the main route_request method for prefill phase"""
    router = DisaggregatedQoERouter()

    # Create mixed endpoints
    endpoints = [
        EndpointInfo(url="http://vllm-prefill-1.com"),
        EndpointInfo(url="http://vllm-prefill-2.com"),
        EndpointInfo(url="http://vllm-decoding-1.com"),
        EndpointInfo(url="http://vllm-decoding-2.com"),
    ]

    # Create engine stats
    engine_stats = {
        "http://vllm-prefill-1.com": EngineStats(
            num_running_requests=5,
            num_queuing_requests=1,
            gpu_prefix_cache_hit_rate=0.8,
            gpu_cache_usage_perc=0.5,
        ),
        "http://vllm-prefill-2.com": EngineStats(
            num_running_requests=3,
            num_queuing_requests=0,
            gpu_prefix_cache_hit_rate=0.7,
            gpu_cache_usage_perc=0.4,
        ),
        "http://vllm-decoding-1.com": EngineStats(
            num_running_requests=5,
            num_queuing_requests=2,
            gpu_prefix_cache_hit_rate=0.5,
            gpu_cache_usage_perc=0.6,
        ),
        "http://vllm-decoding-2.com": EngineStats(
            num_running_requests=8,
            num_queuing_requests=1,
            gpu_prefix_cache_hit_rate=0.4,
            gpu_cache_usage_perc=0.7,
        ),
    }

    # Create request stats
    request_stats = {
        "http://vllm-prefill-1.com": RequestStats(
            qps=10.0,
            ttft=0.25,
            in_prefill_requests=5,
            in_decoding_requests=0,
            finished_requests=100,
            uptime=3600,
            avg_decoding_length=0.0,
            avg_latency=2.0,
            avg_itl=0.0,
            num_swapped_requests=0,
        ),
        "http://vllm-prefill-2.com": RequestStats(
            qps=8.0,
            ttft=0.15,  # Better TTFT
            in_prefill_requests=3,
            in_decoding_requests=0,
            finished_requests=80,
            uptime=3600,
            avg_decoding_length=0.0,
            avg_latency=1.8,
            avg_itl=0.0,
            num_swapped_requests=0,
        ),
        "http://vllm-decoding-1.com": RequestStats(
            qps=15.0,
            ttft=0.3,
            in_prefill_requests=0,
            in_decoding_requests=5,
            finished_requests=150,
            uptime=3600,
            avg_decoding_length=8.0,
            avg_latency=2.5,
            avg_itl=0.04,
            num_swapped_requests=0,
        ),
        "http://vllm-decoding-2.com": RequestStats(
            qps=12.0,
            ttft=0.35,
            in_prefill_requests=0,
            in_decoding_requests=8,
            finished_requests=120,
            uptime=3600,
            avg_decoding_length=10.0,
            avg_latency=2.8,
            avg_itl=0.02,  # Better ITL
            num_swapped_requests=0,
        ),
    }

    # Test prefill routing
    request = MockRequest(
        headers={"x-request-id": "test-req-3", "x-request-priority": "1"},
        json_data={"messages": [{"role": "user", "content": "Hello"}]},
    )

    url = router.route_request(endpoints, engine_stats, request_stats, request)

    # Should choose a prefill endpoint with best TTFT
    assert url == "http://vllm-prefill-2.com"

    # Check that request tracking was created
    assert "test-req-3" in router.request_tracking


def test_route_request_decoding_phase():
    """Test the main route_request method for decoding phase"""
    router = DisaggregatedQoERouter()

    # Create mixed endpoints
    endpoints = [
        EndpointInfo(url="http://vllm-prefill-1.com"),
        EndpointInfo(url="http://vllm-prefill-2.com"),
        EndpointInfo(url="http://vllm-decoding-1.com"),
        EndpointInfo(url="http://vllm-decoding-2.com"),
    ]

    # Create engine stats
    engine_stats = {
        "http://vllm-prefill-1.com": EngineStats(
            num_running_requests=5,
            num_queuing_requests=1,
            gpu_prefix_cache_hit_rate=0.8,
            gpu_cache_usage_perc=0.5,
        ),
        "http://vllm-prefill-2.com": EngineStats(
            num_running_requests=3,
            num_queuing_requests=0,
            gpu_prefix_cache_hit_rate=0.7,
            gpu_cache_usage_perc=0.4,
        ),
        "http://vllm-decoding-1.com": EngineStats(
            num_running_requests=5,
            num_queuing_requests=2,
            gpu_prefix_cache_hit_rate=0.5,
            gpu_cache_usage_perc=0.6,
        ),
        "http://vllm-decoding-2.com": EngineStats(
            num_running_requests=8,
            num_queuing_requests=1,
            gpu_prefix_cache_hit_rate=0.4,
            gpu_cache_usage_perc=0.7,
        ),
    }

    # Create request stats
    request_stats = {
        "http://vllm-prefill-1.com": RequestStats(
            qps=10.0,
            ttft=0.25,
            in_prefill_requests=5,
            in_decoding_requests=0,
            finished_requests=100,
            uptime=3600,
            avg_decoding_length=0.0,
            avg_latency=2.0,
            avg_itl=0.0,
            num_swapped_requests=0,
        ),
        "http://vllm-prefill-2.com": RequestStats(
            qps=8.0,
            ttft=0.15,  # Better TTFT
            in_prefill_requests=3,
            in_decoding_requests=0,
            finished_requests=80,
            uptime=3600,
            avg_decoding_length=0.0,
            avg_latency=1.8,
            avg_itl=0.0,
            num_swapped_requests=0,
        ),
        "http://vllm-decoding-1.com": RequestStats(
            qps=15.0,
            ttft=0.3,
            in_prefill_requests=0,
            in_decoding_requests=5,
            finished_requests=150,
            uptime=3600,
            avg_decoding_length=8.0,
            avg_latency=2.5,
            avg_itl=0.04,
            num_swapped_requests=0,
        ),
        "http://vllm-decoding-2.com": RequestStats(
            qps=12.0,
            ttft=0.35,
            in_prefill_requests=0,
            in_decoding_requests=8,
            finished_requests=120,
            uptime=3600,
            avg_decoding_length=10.0,
            avg_latency=2.8,
            avg_itl=0.02,  # Better ITL
            num_swapped_requests=0,
        ),
    }

    # Setup request tracking with existing prefill data
    request_id = "test-req-4"
    router.request_tracking[request_id] = {
        "prefill_start_time": time.time() - 0.3,  # 300ms ago
        "prefill_endpoint": "http://vllm-prefill-1.com",
        "priority": 1.0,
    }

    # Test decoding routing
    request = MockRequest(
        headers={"x-request-id": request_id, "x-request-priority": "1"},
        json_data={
            "previous_message_id": "123",
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there"},
            ],
        },
    )

    url = router.route_request(endpoints, engine_stats, request_stats, request)

    # Should choose a decoding endpoint with best ITL
    assert url == "http://vllm-decoding-2.com"

    # Check that request tracking was updated
    assert "decoding_start_time" in router.request_tracking[request_id]
    assert (
        router.request_tracking[request_id]["decoding_endpoint"]
        == "http://vllm-decoding-2.com"
    )


def test_on_request_complete():
    """Test request completion tracking"""
    router = DisaggregatedQoERouter()

    # Setup request tracking with both prefill and decoding data
    request_id = "test-req-5"
    current_time = time.time()
    router.request_tracking[request_id] = {
        "prefill_start_time": current_time - 0.5,  # 500ms ago
        "prefill_endpoint": "http://vllm-prefill-1.com",
        "decoding_start_time": current_time - 0.3,  # 300ms ago
        "decoding_endpoint": "http://vllm-decoding-1.com",
        "priority": 1.0,
    }

    # Mock logger to capture log messages
    with patch("vllm_router.routers.disaggregated_qoe_router.logger") as mock_logger:
        router.on_request_complete(request_id)

        # Verify that logger was called with appropriate information
        mock_logger.info.assert_called()

        # Check request tracking cleanup
        assert request_id not in router.request_tracking


def test_on_request_complete_with_failure():
    """Test request completion with failure"""
    router = DisaggregatedQoERouter()

    # Setup request tracking
    request_id = "test-req-failure"
    router.request_tracking[request_id] = {
        "prefill_start_time": time.time() - 0.5,
        "prefill_endpoint": "http://vllm-prefill-1.com",
        "priority": 1.0,
    }

    # Mark as failed
    router.on_request_complete(request_id, success=False)

    # Check that tracking data is still there but marked as failed
    assert request_id in router.request_tracking
    assert router.request_tracking[request_id]["failed"] is True
