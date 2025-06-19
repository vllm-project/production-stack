#!/usr/bin/env python3

import argparse
import json
import logging
import os
import re
import time
import uuid
from collections import deque
from typing import Dict, List

import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class Colors:
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    NC = "\033[0m"


def print_status(message: str):
    print(f"{Colors.GREEN}[INFO]{Colors.NC} {message}")


def print_error(message: str):
    print(f"{Colors.RED}[ERROR]{Colors.NC} {message}")


def print_warning(message: str):
    print(f"{Colors.YELLOW}[WARNING]{Colors.NC} {message}")


class StaticDiscoveryTest:
    def __init__(
        self,
        router_url: str = "http://localhost:30080",
        model: str = "facebook/opt-125m",
        log_file_path: str = "router.log",
    ):
        self.router_url = router_url
        self.model = model
        self.log_file_path = log_file_path
        self.request_id_to_endpoint = {}
        self.results_dir = f"/tmp/static-discovery-results-{int(time.time())}"
        os.makedirs(self.results_dir, exist_ok=True)

    def send_request(self, request_id: str) -> bool:
        """Send a single request and track which endpoint it goes to"""
        try:
            payload = {
                "model": self.model,
                "prompt": f"This is request {request_id}. Please respond briefly.",
                "temperature": 0.7,
                "max_tokens": 10,
            }

            headers = {
                "Content-Type": "application/json",
                "Authorization": "Bearer dummy",
                "X-Request-Id": request_id,
            }

            response = requests.post(
                f"{self.router_url}/v1/completions",
                json=payload,
                headers=headers,
                timeout=30,
            )

            response.raise_for_status()

            print_status(f"✅ Request {request_id} completed successfully")
            return True

        except requests.exceptions.RequestException as e:
            print_error(f"ERROR: Request {request_id} failed: {e}")
            return False
        except json.JSONDecodeError as e:
            print_error(f"ERROR: Invalid JSON response for request {request_id}: {e}")
            return False

    def test_roundrobin_routing(self, num_requests: int = 20) -> bool:
        """Test that requests are distributed in round-robin fashion"""
        print_status(f"🧪 Testing round-robin routing with {num_requests} requests")

        success_count = 0
        for i in range(1, num_requests + 1):
            request_id = str(uuid.uuid4())
            self.request_id_to_endpoint[request_id] = None
            if self.send_request(request_id):
                success_count += 1
            time.sleep(0.1)  # Small delay between requests

        if success_count == num_requests:
            print_status(f"✅ All {num_requests} requests completed successfully")
        else:
            print_error(f"❌ Only {success_count}/{num_requests} requests succeeded")
            return False

        # Verify that the requests are distributed in round-robin fashion
        # Get router logs
        try:
            with open(self.log_file_path, "r") as f:
                content = deque(f, maxlen=5000)
        except FileNotFoundError:
            print_error(f"❌ Log file not found: {self.log_file_path}")
            return False
        except Exception:
            print_error(f"❌ Error reading log file {self.log_file_path}")
            return False

        # Filter for routing decisions
        routing_lines = []
        for line in content:
            if (
                re.search(r"Routing request.*to.*at.*process time", line)
                and "/health" not in line
            ):
                routing_lines.append(line)

        try:
            with open(f"{self.results_dir}/routing_lines.txt", "w") as f:
                f.write("\n".join(routing_lines))
        except Exception:
            print_error(
                f"❌ Failed to write routing lines to file: {self.results_dir}/routing_lines.txt"
            )
            return False

        print_status(
            f"Wrote {len(routing_lines)} routing lines to {self.results_dir}/routing_lines.txt"
        )

        # Get request ID -> endpoint mapping
        for line in routing_lines:
            match = re.search(
                r"Routing request ([^ ]*) with session id [^ ]* to ([^ ]*) at ", line
            )
            if match:
                request_id = match.group(1)
                endpoint = match.group(2)
                if request_id in self.request_id_to_endpoint:
                    self.request_id_to_endpoint[request_id] = endpoint

        print_status(f"Request ID to endpoint mapping: {self.request_id_to_endpoint}")
        if None in self.request_id_to_endpoint.values():
            print_error("❌ Some requests were not routed to any endpoint")
            return False

        # Verify round-robin distribution
        endpoints = list(self.request_id_to_endpoint.values())
        if len(endpoints) < 2:
            print_warning("Not enough requests to verify round-robin distribution")
            return True

        # Check if endpoints alternate in round-robin fashion
        for i in range(1, len(endpoints)):
            if endpoints[i] == endpoints[i - 1]:
                print_error(
                    f"❌ Round-robin routing failed: consecutive requests {i-1} and {i} went to same endpoint {endpoints[i]}"
                )
                return False

        print_status("✅ Round-robin routing verification passed")
        return True

    def test_health_endpoint(self) -> bool:
        """Test router health endpoint"""
        try:
            response = requests.get(f"{self.router_url}/health", timeout=10)
            response.raise_for_status()
            print_status("✅ Health endpoint is working")
            return True
        except Exception as e:
            print_error(f"❌ Health endpoint failed: {e}")
            return False

    def test_model_listing(self) -> bool:
        """Test that the router can list available models"""
        try:
            response = requests.get(f"{self.router_url}/v1/models", timeout=10)
            response.raise_for_status()
            models_data = response.json()

            if "data" in models_data and len(models_data["data"]) > 0:
                print_status(f"✅ Model listing works, models: {models_data['data']}")
                return True
            else:
                print_error("❌ No models found in listing")
                return False
        except Exception as e:
            print_error(f"❌ Model listing failed: {e}")
            return False

    def run_test(self) -> bool:
        """Run the complete static discovery test"""
        try:
            print_status("🚀 Starting static discovery E2E test")

            # Test health endpoint
            if not self.test_health_endpoint():
                return False

            # Test model listing
            if not self.test_model_listing():
                return False

            # Test round-robin routing
            if not self.test_roundrobin_routing():
                return False

            print_status("✅ Static discovery E2E test passed!")
            return True

        except Exception as e:
            print_error(f"Unexpected error during test: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(
        description="Test static discovery with roundrobin routing"
    )
    parser.add_argument(
        "--router-url", default="http://localhost:30080", help="Router URL"
    )
    parser.add_argument(
        "--model", default="facebook/opt-125m", help="Model to use for testing"
    )
    parser.add_argument(
        "--num-requests", type=int, default=20, help="Number of requests to test"
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument(
        "--log-file-path", default="router.log", help="Path to router log file"
    )

    args = parser.parse_args()

    test = StaticDiscoveryTest(
        router_url=args.router_url, model=args.model, log_file_path=args.log_file_path
    )

    success = test.run_test()
    exit(0 if success else 1)


if __name__ == "__main__":
    main()
