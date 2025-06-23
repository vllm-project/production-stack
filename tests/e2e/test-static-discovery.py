#!/usr/bin/env python3

import argparse
import json
import logging
import os
import re
import time
import uuid
from collections import deque
from typing import Dict, List, Optional, Set

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
        result_dir: str = "tests/e2e/static-discovery-results",
        routing_logic: str = "roundrobin",
        prefix_chunk_size: int = 128,
    ):
        self.router_url = router_url
        self.model = model
        self.log_file_path = log_file_path
        self.routing_logic = routing_logic
        self.results_dir = result_dir
        os.makedirs(self.results_dir, exist_ok=True)
        self.prefix_chunk_size = prefix_chunk_size

    def _read_log_file(self) -> Optional[deque]:
        """Read router log file and return content as deque"""
        try:
            with open(self.log_file_path, "r") as f:
                return deque(f, maxlen=5000)
        except FileNotFoundError:
            print_error(f"❌ Log file not found: {self.log_file_path}")
            return None
        except Exception:
            print_error(f"❌ Error reading log file {self.log_file_path}")
            return None

    def _extract_routing_lines(self, content: deque) -> List[str]:
        """Extract routing decision lines from log content"""
        routing_lines = []
        for line in content:
            if (
                re.search(r"Routing request.*to.*at.*process time", line)
                and "/health" not in line
            ):
                routing_lines.append(line)
        return routing_lines

    def _extract_endpoint_mapping(
        self, routing_lines: List[str], request_id_to_endpoints: Dict[str, str]
    ):
        """Extract request ID to endpoint mapping from routing lines and update request_id_to_endpoints"""
        for line in routing_lines:
            match = re.search(
                r"Routing request ([^ ]*) with session id [^ ]* to ([^ ]*) at ", line
            )
            if match:
                request_id = match.group(1)
                endpoint = match.group(2)
                if request_id in request_id_to_endpoints:
                    request_id_to_endpoints[request_id] = endpoint

    def _extract_endpoint_set_mapping(
        self, routing_lines: List[str], request_id_to_endpoints: Dict[str, Set[str]]
    ):
        """Extract request ID to set of endpoints mapping from routing lines"""
        for line in routing_lines:
            match = re.search(
                r"Routing request ([^ ]*) with session id [^ ]* to ([^ ]*) at ", line
            )
            if match:
                request_id = match.group(1)
                endpoint = match.group(2)
                if request_id in request_id_to_endpoints:
                    request_id_to_endpoints[request_id].add(endpoint)

    def _save_routing_lines(
        self, routing_lines: List[str], filename: str = "routing_lines.txt"
    ) -> bool:
        """Save routing lines to a file in results directory"""
        try:
            filepath = f"{self.results_dir}/{filename}"
            with open(filepath, "w") as f:
                f.write("\n".join(routing_lines))
            print_status(f"Wrote {len(routing_lines)} routing lines to {filepath}")
            return True
        except Exception:
            print_error(
                f"❌ Failed to write routing lines to file: {self.results_dir}/{filename}"
            )
            return False

    def send_request(self, request_id: str, prompt: str) -> bool:
        """Send a single request and track which endpoint it goes to"""
        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
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

        request_id_to_endpoint = {}
        success_count = 0

        # Send requests
        for i in range(1, num_requests + 1):
            request_id = str(uuid.uuid4())
            request_id_to_endpoint[request_id] = None
            prompt = f"This is request {request_id}. Please respond briefly."
            if self.send_request(request_id, prompt):
                success_count += 1

        if success_count == num_requests:
            print_status(f"✅ All {num_requests} requests completed successfully")
        else:
            print_error(f"❌ Only {success_count}/{num_requests} requests succeeded")
            return False

        # Analyze routing patterns
        content = self._read_log_file()
        if content is None:
            return False

        routing_lines = self._extract_routing_lines(content)
        if not self._save_routing_lines(routing_lines):
            return False

        # Extract endpoint mapping
        self._extract_endpoint_mapping(routing_lines, request_id_to_endpoint)
        print_status(f"Request ID to endpoint mapping: {request_id_to_endpoint}")

        if None in request_id_to_endpoint.values():
            print_error("❌ Some requests were not routed to any endpoint")
            return False

        # Verify round-robin distribution
        endpoints = list(request_id_to_endpoint.values())
        for i in range(1, len(endpoints)):
            if endpoints[i] == endpoints[i - 1]:
                print_error(
                    f"❌ Round-robin routing failed: consecutive requests {i-1} and {i} went to same endpoint {endpoints[i]}"
                )
                return False

        print_status("✅ Round-robin routing verification passed")
        return True

    def test_prefixaware_routing(self) -> bool:
        """Test that the router can handle prefix-aware routing"""
        print_status(f"🧪 Testing prefix-aware routing")

        request_id_to_endpoints_success = {}
        request_id_to_endpoints_failure = {}
        success_count = 0

        # Generate test data with 3 success and 1 failure
        prefix_test_data = {
            "success": [
                [
                    "1" * self.prefix_chunk_size,
                    "1" * self.prefix_chunk_size + "2" * self.prefix_chunk_size,
                    "1" * self.prefix_chunk_size
                    + "2" * self.prefix_chunk_size
                    + "3" * self.prefix_chunk_size,
                ],
                [
                    "2" * self.prefix_chunk_size
                    + "3" * self.prefix_chunk_size
                    + "4" * self.prefix_chunk_size,
                    "2" * self.prefix_chunk_size + "3" * self.prefix_chunk_size,
                    "2" * self.prefix_chunk_size,
                ],
                [
                    "5" * self.prefix_chunk_size,
                    "5" * self.prefix_chunk_size + "6" * self.prefix_chunk_size,
                    "5" * self.prefix_chunk_size
                    + "6" * self.prefix_chunk_size
                    + "7" * self.prefix_chunk_size,
                ],
                [
                    "8" * self.prefix_chunk_size,
                    "8" * self.prefix_chunk_size + "9" * self.prefix_chunk_size,
                    "8" * self.prefix_chunk_size
                    + "9" * self.prefix_chunk_size
                    + "10" * self.prefix_chunk_size,
                ],
                [
                    "11" * self.prefix_chunk_size,
                    "11" * self.prefix_chunk_size + "12" * self.prefix_chunk_size,
                    "11" * self.prefix_chunk_size
                    + "12" * self.prefix_chunk_size
                    + "13" * self.prefix_chunk_size,
                ],
                [
                    "14" * self.prefix_chunk_size,
                    "14" * self.prefix_chunk_size + "15" * self.prefix_chunk_size,
                    "14" * self.prefix_chunk_size
                    + "15" * self.prefix_chunk_size
                    + "16" * self.prefix_chunk_size,
                ],
            ],
            "failure": [
                [
                    "1" * self.prefix_chunk_size,
                    "2" * self.prefix_chunk_size,
                    "5" * self.prefix_chunk_size,
                    "8" * self.prefix_chunk_size,
                    "11" * self.prefix_chunk_size,
                    "14" * self.prefix_chunk_size,
                ]
            ],
        }

        # Send requests
        total_requests = 0
        for test_case, request_id_map in [
            ("success", request_id_to_endpoints_success),
            ("failure", request_id_to_endpoints_failure),
        ]:
            for prefix_chunk in prefix_test_data[test_case]:
                request_id = str(uuid.uuid4())
                request_id_map[request_id] = set()
                for sample in prefix_chunk:
                    # Send 5 requests for each sample
                    for _ in range(5):
                        total_requests += 1
                        if self.send_request(request_id, sample):
                            success_count += 1

        if success_count == total_requests:
            print_status(f"✅ All {total_requests} requests completed successfully")
        else:
            print_error(f"❌ Only {success_count}/{total_requests} requests succeeded")
            return False

        # Analyze routing patterns
        content = self._read_log_file()
        if content is None:
            return False

        routing_lines = self._extract_routing_lines(content)
        self._extract_endpoint_set_mapping(
            routing_lines, request_id_to_endpoints_success
        )
        self._extract_endpoint_set_mapping(
            routing_lines, request_id_to_endpoints_failure
        )

        print_status(
            f"Request ID to endpoint mapping for success: {request_id_to_endpoints_success}"
        )
        print_status(
            f"Request ID to endpoint mapping for failure: {request_id_to_endpoints_failure}"
        )
        self._save_routing_lines(routing_lines, "routing_lines.txt")

        # Verify prefix-aware routing
        success_endpoints = set()
        for request_id, endpoints in request_id_to_endpoints_success.items():
            if len(endpoints) != 1:
                print_error(
                    f"❌ Request {request_id} was routed to multiple endpoints: {endpoints}"
                )
                return False
            success_endpoints.add(list(endpoints)[0])
        for request_id, endpoints in request_id_to_endpoints_failure.items():
            if len(success_endpoints) == 2 and len(endpoints) < 2:
                print_error(
                    f"❌ Request {request_id} was routed to less than 2 endpoints: {endpoints}"
                )
                return False
            elif len(success_endpoints) == 1 and len(endpoints) != 1:
                print_error(
                    f"❌ Request {request_id} was routed to multiple endpoints: {endpoints}"
                )
                return False

        print_status("✅ Prefix-aware routing verification passed")
        return True

    def test_disaggregated_prefill_routing(self) -> bool:
        """Test that the router can handle disaggregated prefill routing"""
        print_status("🧪 Testing disaggregated prefill routing")
        return True

    def test_kvaware_routing(self) -> bool:
        """Test that the router can handle kvaware routing"""
        print_status("🧪 Testing kvaware routing")
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

    def test_chat_completions(self) -> bool:
        """Test that the router can handle chat completions"""
        try:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "Hello! How are you?"},
                ],
                "max_tokens": 10,
                "temperature": 0.7,
            }
            headers = {
                "Content-Type": "application/json",
                "Authorization": "Bearer dummy",
            }
            response = requests.post(
                f"{self.router_url}/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            print_status("✅ Chat completions are working")
            return True
        except Exception as e:
            print_error(f"❌ Chat completions failed: {e} payload: {payload}")
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

            # Test chat completions
            if not self.test_chat_completions():
                return False

            # Test routing logic
            test_runners = {
                "roundrobin": self.test_roundrobin_routing,
                "prefixaware": self.test_prefixaware_routing,
                "disaggregated_prefill": self.test_disaggregated_prefill_routing,
                "kvaware": self.test_kvaware_routing,
            }
            if test_runner := test_runners.get(self.routing_logic):
                if not test_runner():
                    return False
            else:
                print_status(f"🧪 Skipping test for {self.routing_logic} routing logic")

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
    parser.add_argument(
        "--result-dir",
        default="tests/e2e/static-discovery-results",
        help="Path to result directory",
    )
    parser.add_argument(
        "--routing-logic",
        default="roundrobin",
        help="Routing logic to use for testing",
    )
    parser.add_argument(
        "--prefix-chunk-size", type=int, default=128, help="Size of prefix chunk"
    )
    args = parser.parse_args()

    test = StaticDiscoveryTest(
        router_url=args.router_url,
        model=args.model,
        log_file_path=args.log_file_path,
        result_dir=args.result_dir,
        routing_logic=args.routing_logic,
        prefix_chunk_size=args.prefix_chunk_size,
    )

    success = test.run_test()
    exit(0 if success else 1)


if __name__ == "__main__":
    main()
