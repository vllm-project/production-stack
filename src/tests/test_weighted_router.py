import unittest
import time
from collections import Counter
from fastapi import Request
from unittest.mock import MagicMock

from vllm_router.routing_logic import WeightedRouter
from vllm_router.service_discovery import EndpointInfo


class TestWeightedRouter(unittest.TestCase):
    def setUp(self):
        # Create test endpoints with current timestamp
        current_time = time.time()
        self.endpoints = [
            EndpointInfo(url="http://endpoint1:8000", model_name="model1", added_timestamp=current_time),
            EndpointInfo(url="http://endpoint2:8000", model_name="model1", added_timestamp=current_time),
            EndpointInfo(url="http://endpoint3:8000", model_name="model1", added_timestamp=current_time),
        ]
        
        # Configure weights (50%, 30%, 20%)
        self.weights = {
            "http://endpoint1:8000": 51,
            "http://endpoint2:8000": 27,
            "http://endpoint3:8000": 22,
        }
        
        # Initialize router
        self.router = WeightedRouter(weights=self.weights)
        
        # Create mock request, engine stats and request stats
        self.mock_request = MagicMock(spec=Request)
        self.mock_engine_stats = {}
        self.mock_request_stats = {}

    def test_weight_distribution(self):
        """Test if requests are distributed according to the configured weights."""
        # Number of requests to simulate
        num_requests = 1000
        
        # Collect routing decisions
        routing_results = Counter()
        for _ in range(num_requests):
            chosen_url = self.router.route_request(
                self.endpoints,
                self.mock_engine_stats,
                self.mock_request_stats,
                self.mock_request
            )
            routing_results[chosen_url] += 1
        
        # Calculate actual distribution percentages
        total_requests = sum(routing_results.values())
        actual_distribution = {
            url: (count / total_requests) * 100
            for url, count in routing_results.items()
        }
        
        # Define acceptable margin of error (in percentage points)
        margin = 5.0
        # Print actual distribution
        print(f"Actual distribution: {actual_distribution}")
        # Verify distribution matches configured weights within margin
        for url, expected_weight in self.weights.items():
            actual_weight = actual_distribution[url]
            self.assertAlmostEqual(
                actual_weight,
                expected_weight,
                delta=margin,
                msg=f"Distribution for {url} ({actual_weight:.1f}%) differs from expected weight ({expected_weight}%) by more than {margin}%"
            )

    def test_dynamic_endpoint_changes(self):
        """Test if router handles endpoint changes correctly."""
        # Initial routing with all endpoints
        url1 = self.router.route_request(
            self.endpoints,
            self.mock_engine_stats,
            self.mock_request_stats,
            self.mock_request
        )
        self.assertIn(url1, self.weights.keys())
        
        # Remove one endpoint
        reduced_endpoints = self.endpoints[1:]  # Remove first endpoint
        url2 = self.router.route_request(
            reduced_endpoints,
            self.mock_engine_stats,
            self.mock_request_stats,
            self.mock_request
        )
        self.assertIn(url2, [ep.url for ep in reduced_endpoints])
        
        # Add back all endpoints
        url3 = self.router.route_request(
            self.endpoints,
            self.mock_engine_stats,
            self.mock_request_stats,
            self.mock_request
        )
        self.assertIn(url3, self.weights.keys())

    def test_missing_weights(self):
        """Test if router handles endpoints without configured weights."""
        # Create router with weights for only some endpoints
        partial_weights = {
            "http://endpoint1:8000": 50,
            "http://endpoint2:8000": 50,
        }
        router = WeightedRouter(weights=partial_weights)
        
        # Route requests and verify all endpoints are still used
        used_endpoints = set()
        for _ in range(100):
            url = router.route_request(
                self.endpoints,
                self.mock_engine_stats,
                self.mock_request_stats,
                self.mock_request
            )
            used_endpoints.add(url)
        
        # Verify all endpoints are used, even those without configured weights
        self.assertEqual(
            used_endpoints,
            {ep.url for ep in self.endpoints},
            "Not all endpoints were used in routing"
        )

    def test_smooth_distribution(self):
        """Test if the distribution is smooth without bursts."""
        # Track consecutive selections of the same endpoint
        max_consecutive = {url: 0 for url in self.weights}
        current_consecutive = {url: 0 for url in self.weights}
        last_url = None
        
        # Route a significant number of requests
        num_requests = 1000
        for _ in range(num_requests):
            url = self.router.route_request(
                self.endpoints,
                self.mock_engine_stats,
                self.mock_request_stats,
                self.mock_request
            )
            
            # Update consecutive counts
            for endpoint_url in self.weights:
                if url == endpoint_url:
                    current_consecutive[url] += 1
                    max_consecutive[url] = max(
                        max_consecutive[url],
                        current_consecutive[url]
                    )
                else:
                    current_consecutive[endpoint_url] = 0
            
            last_url = url
        
        # Check that no endpoint was selected too many times in a row
        # For SWRR, the maximum consecutive selections should be relatively small
        for url, weight in self.weights.items():
            expected_max = (weight / 10) + 2  # Heuristic threshold
            self.assertLess(
                max_consecutive[url],
                expected_max,
                f"Endpoint {url} was selected {max_consecutive[url]} times consecutively, "
                f"which is more than expected ({expected_max}) for its weight {weight}%"
            )


if __name__ == '__main__':
    unittest.main() 