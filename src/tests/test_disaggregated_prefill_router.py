from typing import Dict

import pytest

from vllm_router.routers.routing_logic import (
    DisaggregatedPrefillRouter,
    LoadBalancingStrategy,
)


class EndpointInfo:
    def __init__(self, url: str, model_label: str):
        self.url = url
        self.model_label = model_label


class RequestStats:
    def __init__(self, qps: float):
        self.qps = qps


class Request:
    def __init__(self, headers: Dict[str, str]):
        self.headers = headers


class TestDisaggregatedPrefillRouter:
    def setup_method(self):
        """Setup test fixtures before each test method."""
        self.prefill_endpoints = [
            EndpointInfo("http://prefill1.com", "prefill-model"),
            EndpointInfo("http://prefill2.com", "prefill-model"),
            EndpointInfo("http://prefill3.com", "prefill-model"),
        ]
        self.decode_endpoints = [
            EndpointInfo("http://decode1.com", "decode-model"),
            EndpointInfo("http://decode2.com", "decode-model"),
            EndpointInfo("http://decode3.com", "decode-model"),
        ]
        self.all_endpoints = self.prefill_endpoints + self.decode_endpoints

        self.request_stats = {
            "http://prefill1.com": RequestStats(qps=10.0),
            "http://prefill2.com": RequestStats(qps=5.0),
            "http://prefill3.com": RequestStats(qps=15.0),
            "http://decode1.com": RequestStats(qps=8.0),
            "http://decode2.com": RequestStats(qps=3.0),
            "http://decode3.com": RequestStats(qps=12.0),
        }

        self.mock_request = Request(headers={})
        self.mock_engine_stats = {}

    def test_round_robin_prefill_routing(self):
        """Test round-robin load balancing for prefill requests."""
        router = DisaggregatedPrefillRouter(
            prefill_model_labels=["prefill-model"],
            decode_model_labels=["decode-model"],
            load_balancing_strategy=LoadBalancingStrategy.ROUND_ROBIN,
        )

        # Test multiple prefill requests (max_tokens=1)
        prefill_request_json = {"max_tokens": 1}

        results = []
        for _ in range(6):  # Test twice the number of endpoints
            result = router.route_request(
                self.all_endpoints,
                self.mock_engine_stats,
                self.request_stats,
                self.mock_request,
                prefill_request_json,
            )
            results.append(result)

        # Verify round-robin behavior
        expected_sequence = [
            "http://prefill1.com",
            "http://prefill2.com",
            "http://prefill3.com",
            "http://prefill1.com",
            "http://prefill2.com",
            "http://prefill3.com",
        ]
        assert results == expected_sequence

    def test_round_robin_decode_routing(self):
        """Test round-robin load balancing for decode requests."""
        router = DisaggregatedPrefillRouter(
            prefill_model_labels=["prefill-model"],
            decode_model_labels=["decode-model"],
            load_balancing_strategy=LoadBalancingStrategy.ROUND_ROBIN,
        )

        # Test multiple decode requests (max_tokens != 1)
        decode_request_json = {"max_tokens": 100}

        results = []
        for _ in range(6):  # Test twice the number of endpoints
            result = router.route_request(
                self.all_endpoints,
                self.mock_engine_stats,
                self.request_stats,
                self.mock_request,
                decode_request_json,
            )
            results.append(result)

        # Verify round-robin behavior
        expected_sequence = [
            "http://decode1.com",
            "http://decode2.com",
            "http://decode3.com",
            "http://decode1.com",
            "http://decode2.com",
            "http://decode3.com",
        ]
        assert results == expected_sequence

    def test_random_load_balancing(self):
        """Test random load balancing strategy."""
        router = DisaggregatedPrefillRouter(
            prefill_model_labels=["prefill-model"],
            decode_model_labels=["decode-model"],
            load_balancing_strategy=LoadBalancingStrategy.RANDOM,
        )

        prefill_request_json = {"max_tokens": 1}
        decode_request_json = {"max_tokens": 100}

        # Test prefill routing - should return one of the prefill endpoints
        prefill_results = set()
        for _ in range(20):  # Run multiple times to test randomness
            result = router.route_request(
                self.all_endpoints,
                self.mock_engine_stats,
                self.request_stats,
                self.mock_request,
                prefill_request_json,
            )
            prefill_results.add(result)

        # Should only return prefill endpoints
        expected_prefill_urls = {
            "http://prefill1.com",
            "http://prefill2.com",
            "http://prefill3.com",
        }
        assert prefill_results.issubset(expected_prefill_urls)

        # Test decode routing - should return one of the decode endpoints
        decode_results = set()
        for _ in range(20):  # Run multiple times to test randomness
            result = router.route_request(
                self.all_endpoints,
                self.mock_engine_stats,
                self.request_stats,
                self.mock_request,
                decode_request_json,
            )
            decode_results.add(result)

        # Should only return decode endpoints
        expected_decode_urls = {
            "http://decode1.com",
            "http://decode2.com",
            "http://decode3.com",
        }
        assert decode_results.issubset(expected_decode_urls)

    def test_qps_load_balancing(self):
        """Test QPS-based load balancing strategy."""
        router = DisaggregatedPrefillRouter(
            prefill_model_labels=["prefill-model"],
            decode_model_labels=["decode-model"],
            load_balancing_strategy=LoadBalancingStrategy.QPS,
        )

        prefill_request_json = {"max_tokens": 1}
        decode_request_json = {"max_tokens": 100}

        # Test prefill routing - should select endpoint with lowest QPS
        result = router.route_request(
            self.all_endpoints,
            self.mock_engine_stats,
            self.request_stats,
            self.mock_request,
            prefill_request_json,
        )
        # http://prefill2.com has QPS=5.0, which is lowest among prefill endpoints
        assert result == "http://prefill2.com"

        # Test decode routing - should select endpoint with lowest QPS
        result = router.route_request(
            self.all_endpoints,
            self.mock_engine_stats,
            self.request_stats,
            self.mock_request,
            decode_request_json,
        )
        # http://decode2.com has QPS=3.0, which is lowest among decode endpoints
        assert result == "http://decode2.com"

    def test_qps_load_balancing_with_missing_stats(self):
        """Test QPS load balancing when some endpoints don't have stats."""
        router = DisaggregatedPrefillRouter(
            prefill_model_labels=["prefill-model"],
            decode_model_labels=["decode-model"],
            load_balancing_strategy=LoadBalancingStrategy.QPS,
        )

        # Remove stats for one endpoint to simulate new endpoint
        incomplete_stats = self.request_stats.copy()
        del incomplete_stats["http://prefill1.com"]

        prefill_request_json = {"max_tokens": 1}

        result = router.route_request(
            self.all_endpoints,
            self.mock_engine_stats,
            incomplete_stats,
            self.mock_request,
            prefill_request_json,
        )
        # Should select the endpoint without stats (new endpoint)
        assert result == "http://prefill1.com"

    def test_prefill_detection_logic(self):
        """Test correct detection of prefill vs decode requests."""
        router = DisaggregatedPrefillRouter(
            prefill_model_labels=["prefill-model"],
            decode_model_labels=["decode-model"],
            load_balancing_strategy=LoadBalancingStrategy.ROUND_ROBIN,
        )

        # Test prefill detection (max_tokens=1)
        prefill_request_json = {"max_tokens": 1}
        result = router.route_request(
            self.all_endpoints,
            self.mock_engine_stats,
            self.request_stats,
            self.mock_request,
            prefill_request_json,
        )
        assert result in [
            "http://prefill1.com",
            "http://prefill2.com",
            "http://prefill3.com",
        ]

        # Test decode detection (max_tokens != 1)
        decode_request_json = {"max_tokens": 100}
        result = router.route_request(
            self.all_endpoints,
            self.mock_engine_stats,
            self.request_stats,
            self.mock_request,
            decode_request_json,
        )
        assert result in [
            "http://decode1.com",
            "http://decode2.com",
            "http://decode3.com",
        ]

        # Test decode detection (max_tokens=0)
        decode_request_json_zero = {"max_tokens": 0}
        result = router.route_request(
            self.all_endpoints,
            self.mock_engine_stats,
            self.request_stats,
            self.mock_request,
            decode_request_json_zero,
        )
        assert result in [
            "http://decode1.com",
            "http://decode2.com",
            "http://decode3.com",
        ]

    def test_no_prefill_endpoints_available(self):
        """Test error handling when no prefill endpoints are available."""
        router = DisaggregatedPrefillRouter(
            prefill_model_labels=["prefill-model"],
            decode_model_labels=["decode-model"],
            load_balancing_strategy=LoadBalancingStrategy.ROUND_ROBIN,
        )

        # Only provide decode endpoints
        prefill_request_json = {"max_tokens": 1}

        with pytest.raises(ValueError, match="No prefill endpoints available"):
            router.route_request(
                self.decode_endpoints,  # Only decode endpoints
                self.mock_engine_stats,
                self.request_stats,
                self.mock_request,
                prefill_request_json,
            )

    def test_no_decode_endpoints_available(self):
        """Test error handling when no decode endpoints are available."""
        router = DisaggregatedPrefillRouter(
            prefill_model_labels=["prefill-model"],
            decode_model_labels=["decode-model"],
            load_balancing_strategy=LoadBalancingStrategy.ROUND_ROBIN,
        )

        # Only provide prefill endpoints
        decode_request_json = {"max_tokens": 100}

        with pytest.raises(ValueError, match="No decode endpoints available"):
            router.route_request(
                self.prefill_endpoints,  # Only prefill endpoints
                self.mock_engine_stats,
                self.request_stats,
                self.mock_request,
                decode_request_json,
            )

    def test_unknown_load_balancing_strategy_fallback(self):
        """Test fallback behavior for unknown load balancing strategy."""
        # Create router with invalid strategy by setting it directly
        router = DisaggregatedPrefillRouter(
            prefill_model_labels=["prefill-model"],
            decode_model_labels=["decode-model"],
            load_balancing_strategy=LoadBalancingStrategy.ROUND_ROBIN,
        )
        # Manually set invalid strategy
        router.load_balancing_strategy = "invalid_strategy"

        prefill_request_json = {"max_tokens": 1}

        result = router.route_request(
            self.all_endpoints,
            self.mock_engine_stats,
            self.request_stats,
            self.mock_request,
            prefill_request_json,
        )
        # Should fallback to first endpoint
        assert result == "http://prefill1.com"

    def test_independent_counters_for_round_robin(self):
        """Test that prefill and decode requests have independent round-robin counters."""
        router = DisaggregatedPrefillRouter(
            prefill_model_labels=["prefill-model"],
            decode_model_labels=["decode-model"],
            load_balancing_strategy=LoadBalancingStrategy.ROUND_ROBIN,
        )

        prefill_request_json = {"max_tokens": 1}
        decode_request_json = {"max_tokens": 100}

        # Make some prefill requests
        prefill_results = []
        for _ in range(2):
            result = router.route_request(
                self.all_endpoints,
                self.mock_engine_stats,
                self.request_stats,
                self.mock_request,
                prefill_request_json,
            )
            prefill_results.append(result)

        # Make some decode requests
        decode_results = []
        for _ in range(2):
            result = router.route_request(
                self.all_endpoints,
                self.mock_engine_stats,
                self.request_stats,
                self.mock_request,
                decode_request_json,
            )
            decode_results.append(result)

        # Continue with more prefill requests
        for _ in range(2):
            result = router.route_request(
                self.all_endpoints,
                self.mock_engine_stats,
                self.request_stats,
                self.mock_request,
                prefill_request_json,
            )
            prefill_results.append(result)

        # Verify independent round-robin sequences
        expected_prefill = [
            "http://prefill1.com",  # req 0
            "http://prefill2.com",  # req 1
            "http://prefill3.com",  # req 2
            "http://prefill1.com",  # req 3
        ]
        expected_decode = [
            "http://decode1.com",  # req 0
            "http://decode2.com",  # req 1
        ]

        assert prefill_results == expected_prefill
        assert decode_results == expected_decode

    def test_multiple_model_labels(self):
        """Test routing with multiple model labels for prefill and decode."""
        router = DisaggregatedPrefillRouter(
            prefill_model_labels=["prefill-model-1", "prefill-model-2"],
            decode_model_labels=["decode-model-1", "decode-model-2"],
            load_balancing_strategy=LoadBalancingStrategy.ROUND_ROBIN,
        )

        mixed_endpoints = [
            EndpointInfo("http://prefill1.com", "prefill-model-1"),
            EndpointInfo("http://prefill2.com", "prefill-model-2"),
            EndpointInfo("http://decode1.com", "decode-model-1"),
            EndpointInfo("http://decode2.com", "decode-model-2"),
            EndpointInfo("http://other.com", "other-model"),  # Should be ignored
        ]

        prefill_request_json = {"max_tokens": 1}
        decode_request_json = {"max_tokens": 100}

        # Test prefill routing - should use both prefill model endpoints
        prefill_results = []
        for _ in range(4):
            result = router.route_request(
                mixed_endpoints,
                self.mock_engine_stats,
                self.request_stats,
                self.mock_request,
                prefill_request_json,
            )
            prefill_results.append(result)

        expected_prefill = [
            "http://prefill1.com",
            "http://prefill2.com",
            "http://prefill1.com",
            "http://prefill2.com",
        ]
        assert prefill_results == expected_prefill

        # Test decode routing - should use both decode model endpoints
        decode_results = []
        for _ in range(4):
            result = router.route_request(
                mixed_endpoints,
                self.mock_engine_stats,
                self.request_stats,
                self.mock_request,
                decode_request_json,
            )
            decode_results.append(result)

        expected_decode = [
            "http://decode1.com",
            "http://decode2.com",
            "http://decode1.com",
            "http://decode2.com",
        ]
        assert decode_results == expected_decode
