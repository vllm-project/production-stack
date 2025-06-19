#!/usr/bin/env python3

import argparse
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple

import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# Colors for output
class Colors:
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    NC = "\033[0m"  # No Color


def print_status(message: str):
    """Print status message in green"""
    print(f"{Colors.GREEN}[INFO]{Colors.NC} {message}")


def print_error(message: str):
    """Print error message in red"""
    print(f"{Colors.RED}[ERROR]{Colors.NC} {message}")


def print_warning(message: str):
    """Print warning message in yellow"""
    print(f"{Colors.YELLOW}[WARNING]{Colors.NC} {message}")


class PrefixAwareRoutingTest:
    def __init__(
        self,
        base_url: str = "",
        model: str = "facebook/opt-125m",
        num_requests_per_sample: int = 3,
        verbose: bool = False,
        debug: bool = False,
        chunk_size: int = 128,
    ):
        self.base_url = base_url
        self.model = model
        self.num_requests_per_sample = num_requests_per_sample
        self.verbose = verbose
        self.debug = debug
        self.temp_dir = tempfile.mkdtemp()
        self.results_dir = f"/tmp/prefix-aware-routing-results-{int(time.time())}"
        self.port_forward_pid = None
        self.chunk_size = chunk_size

        # Create results directory
        os.makedirs(self.results_dir, exist_ok=True)

        # Load test prefixes
        self.test_prefix_groups = self._load_test_prefix_groups()

    def _load_test_prefix_groups(self) -> List[Tuple[str, List[str]]]:
        """Load test prefixes for routing testing"""
        return [
            # Success case - should route to same endpoint
            (
                "1",
                [
                    "1" * self.chunk_size,
                    "1" * self.chunk_size + "2" * self.chunk_size,
                    "1" * self.chunk_size
                    + "2" * self.chunk_size
                    + "3" * self.chunk_size,
                ],
            ),
            (
                "2",
                [
                    "2" * self.chunk_size
                    + "3" * self.chunk_size
                    + "4" * self.chunk_size,
                    "2" * self.chunk_size + "3" * self.chunk_size,
                    "2" * self.chunk_size,
                ],
            ),
            (
                "3",
                [
                    "5" * self.chunk_size,
                    "5" * self.chunk_size + "6" * self.chunk_size,
                    "5" * self.chunk_size
                    + "6" * self.chunk_size
                    + "7" * self.chunk_size,
                ],
            ),
            (
                "4",
                [
                    "8" * self.chunk_size
                    + "9" * self.chunk_size
                    + "10" * self.chunk_size,
                    "8" * self.chunk_size,
                    "8" * self.chunk_size + "9" * self.chunk_size,
                ],
            ),
            # Failure case - should route to different endpoints
            (
                "5",
                [
                    "1" * self.chunk_size,
                    "2" * self.chunk_size,
                    "5" * self.chunk_size,
                    "8" * self.chunk_size,
                ],
            ),
        ]

    def cleanup(self):
        """Cleanup resources"""
        if self.port_forward_pid:
            print_status(f"Cleaning up port forwarding (PID: {self.port_forward_pid})")
            try:
                os.kill(self.port_forward_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

        if self.debug:
            print_status(f"Debug mode: Preserving temp directory: {self.temp_dir}")
            print_status(f"Debug mode: Results also saved to: {self.results_dir}")
            # Copy all files to results directory
            for file in os.listdir(self.temp_dir):
                src = os.path.join(self.temp_dir, file)
                dst = os.path.join(self.results_dir, file)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
        else:
            # Copy specific files to results directory
            for filename in ["router_logs.txt"]:
                src = os.path.join(self.temp_dir, filename)
                dst = os.path.join(self.results_dir, filename)
                if os.path.exists(src):
                    shutil.copy2(src, dst)

            # Remove temp directory
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def setup_port_forwarding(self) -> bool:
        """Set up port forwarding if base_url is not provided"""
        if self.base_url:
            return True

        # Check if vllm-router-service exists
        try:
            subprocess.run(
                ["kubectl", "get", "svc", "vllm-router-service"],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError:
            print_error(
                "vllm-router-service not found. Please ensure the service exists or provide --base-url"
            )
            return False

        local_port = 30080
        print_status(
            f"Setting up port forwarding to vllm-router-service on localhost:{local_port}"
        )

        # Start port forwarding
        try:
            process = subprocess.Popen(
                [
                    "kubectl",
                    "port-forward",
                    "svc/vllm-router-service",
                    f"{local_port}:80",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.port_forward_pid = process.pid
            time.sleep(3)  # Wait for port forwarding to establish
            self.base_url = f"http://localhost:{local_port}/v1"
            print_status(f"Using port forwarding: {self.base_url}")
            return True
        except Exception as e:
            print_error(f"Failed to set up port forwarding: {e}")
            return False

    def get_router_logs(self) -> Optional[str]:
        """Get router logs from Kubernetes"""
        print_status("Fetching router logs...")

        # Try multiple common router pod selectors
        router_selectors = [
            "environment=router",
            "release=router",
            "app.kubernetes.io/component=router",
            "app=vllmrouter-sample",
        ]

        raw_log_file = os.path.join(self.temp_dir, "raw_router_logs.txt")

        for selector in router_selectors:
            try:
                # Check if pods exist with this selector
                result = subprocess.run(
                    ["kubectl", "get", "pods", "-l", selector, "--no-headers"],
                    capture_output=True,
                    text=True,
                    check=True,
                )

                if result.stdout.strip():
                    print_status(f"Found router pods with selector: {selector}")

                    # Get logs
                    with open(raw_log_file, "w") as f:
                        subprocess.run(
                            ["kubectl", "logs", "-l", selector, "--tail=5000"],
                            stdout=f,
                            stderr=subprocess.PIPE,
                            check=True,
                        )
                    return raw_log_file

            except subprocess.CalledProcessError:
                continue

        print_error("Could not fetch router logs. Router log verification failed.")
        return None

    def verify_routing_consistency(self) -> bool:
        """Verify that routing is consistent based on discovered behavior"""
        print_status("Verifying routing consistency based on discovered behavior...")

        raw_log_file = self.get_router_logs()
        if not raw_log_file:
            return False

        # Filter logs to only include routing decision logs
        router_log_file = os.path.join(self.temp_dir, "router_logs.txt")

        try:
            with open(raw_log_file, "r") as f:
                content = f.read()

            # Filter for routing decisions
            routing_lines = []
            for line in content.split("\n"):
                if (
                    re.search(r"Routing request.*to.*at.*process time", line)
                    and "/health" not in line
                ):
                    routing_lines.append(line)

            # Write filtered logs
            with open(router_log_file, "w") as f:
                f.write("\n".join(routing_lines[-1000:]))  # Last 1000 lines

            if not routing_lines:
                print_error(
                    "No routing decision logs found. Router log verification failed."
                )
                return False

        except Exception as e:
            print_error(f"Error processing router logs: {e}")
            return False

        # Get prefix -> endpoint mapping from logs
        prefix_to_endpoints = {}
        filter_routing_lines = routing_lines[-1000:]
        prefix_group_ids = [prefix_group[0] for prefix_group in self.test_prefix_groups]

        for line in filter_routing_lines:
            match = re.search(
                r"Routing request ([^ ]*) with session id [^ ]* to ([^ ]*) at ", line
            )
            if match:
                prefix_group_id = match.group(1)
                endpoint = match.group(2)
                if prefix_group_id not in prefix_group_ids:
                    continue
                if prefix_group_id not in prefix_to_endpoints:
                    prefix_to_endpoints[prefix_group_id] = set()
                prefix_to_endpoints[prefix_group_id].add(endpoint)

        print_status(f"Prefix to endpoint mapping: {prefix_to_endpoints}")

        # Verify that all requests with the same prefix are routed to the same endpoint
        prefix_with_issues = 0
        for prefix_group_id, endpoints in prefix_to_endpoints.items():
            # Failure case - should route to different endpoints
            if prefix_group_id == "5" and len(endpoints) < 2:
                print_error(
                    f"Prefix group '{prefix_group_id}' is routed to less than 2 endpoints: {endpoints}"
                )
                prefix_with_issues += 1
            # Success case - should route to same endpoint
            elif prefix_group_id != "5" and len(endpoints) > 1:
                print_error(
                    f"Prefix group '{prefix_group_id}' is routed to multiple endpoints: {endpoints}"
                )
                prefix_with_issues += 1

        if prefix_with_issues > 0:
            print_error(
                f"❌ Router verification failed: {prefix_with_issues} prefix groups have routing issues"
            )
            return False
        else:
            print_status(
                "✅ Router verification passed: All prefix groups show consistent routing behavior"
            )
            return True

    def send_request(self, request: str, prefix_group_id: str) -> bool:
        """Send a single request"""
        try:
            prompt = f"This is request: {request}. Please respond briefly."

            payload = {
                "model": self.model,
                "prompt": prompt,
                "temperature": 0.7,
                "max_tokens": 10,
            }

            headers = {
                "Content-Type": "application/json",
                "Authorization": "Bearer dummy",
                "X-Request-Id": prefix_group_id,
            }

            response = requests.post(
                f"{self.base_url}/completions",
                json=payload,
                headers=headers,
                timeout=30,
            )

            response.raise_for_status()

            # Verify response is valid JSON
            response.json()

            if self.verbose:
                print_status(
                    f"✅ Response received for request {request} in prefix group {prefix_group_id}"
                )

            return True

        except requests.exceptions.RequestException as e:
            print_error(
                f"ERROR: Request failed for request {request} in prefix group {prefix_group_id}: {e}"
            )
            return False
        except json.JSONDecodeError as e:
            print_error(
                f"ERROR: Invalid JSON response for request {request} in prefix group {prefix_group_id}: {e}"
            )
            return False

    def send_prefix_requests(self, prefix_group: Tuple[str, List[str]]) -> bool:
        """Send multiple requests for a specific prefix"""
        print_status(
            f"[Prefix group: {prefix_group[0]}] Starting {len(prefix_group[1])} requests, repeated {self.num_requests_per_sample} times"
        )

        prefix_group_id = prefix_group[0]
        requests = prefix_group[1]

        success_count = 0

        # Send requests
        for request_idx, request in enumerate(requests):
            for i in range(1, self.num_requests_per_sample + 1):
                if self.verbose:
                    print_status(
                        f"[Prefix group: {prefix_group_id}] Sending request {request_idx + 1}/{len(requests)} times {i}/{self.num_requests_per_sample}"
                    )
                if self.send_request(request, prefix_group_id):
                    success_count += 1
                else:
                    return False
                time.sleep(0.5)  # Small delay between requests

        if success_count == len(requests) * self.num_requests_per_sample:
            print_status(
                f"[Prefix group: {prefix_group_id}] ✅ All {len(requests)} requests completed successfully"
            )
            return True
        else:
            print_error(
                f"[Prefix group: {prefix_group_id}] ❌ Failed to send {success_count} requests"
            )
            return False

    def send_all_prefix_requests(self) -> bool:
        """Send requests for all prefixes"""
        print_status(f"Sending requests for {len(self.test_prefix_groups)} prefixes")

        failed_prefixes = []

        # Use ThreadPoolExecutor to run all prefixes in parallel
        with ThreadPoolExecutor(
            max_workers=min(len(self.test_prefix_groups), 10)
        ) as executor:
            # Submit all prefix requests
            future_to_prefix = {
                executor.submit(self.send_prefix_requests, prefix_group): prefix_group[
                    0
                ]
                for prefix_group in self.test_prefix_groups
            }

            # Collect results
            for future in future_to_prefix:
                prefix_group_id = future_to_prefix[future]
                try:
                    if future.result():
                        print_status(
                            f"✅ Prefix group '{prefix_group_id}' completed successfully"
                        )
                    else:
                        print_error(f"❌ Prefix group '{prefix_group_id}' failed")
                        failed_prefixes.append(prefix_group_id)
                except Exception as e:
                    print_error(
                        f"❌ Prefix group '{prefix_group_id}' failed with exception: {e}"
                    )
                    failed_prefixes.append(prefix_group_id)

        if failed_prefixes:
            print_error(f"Failed prefixes: {len(failed_prefixes)}")
            return False

        print_status(
            f"✅ All requests completed successfully across {len(self.test_prefix_groups)} prefix groups"
        )
        return True

    def run_test(self) -> bool:
        """Run the complete prefix-aware routing test"""
        try:
            print_status(
                f"Starting prefix-aware routing test with {self.num_requests_per_sample} requests per sample"
            )

            # Set up port forwarding if needed
            if not self.setup_port_forwarding():
                return False

            # Send all prefix requests
            if not self.send_all_prefix_requests():
                return False

            print_status("✅ Prefix request script completed successfully")

            # Verify router logs for prefix-based routing consistency
            if not self.verify_routing_consistency():
                print_error("Router log verification failed!")
                return False

            print_status("✅ Prefix-aware routing test passed!")
            print_status("Router logs confirm consistent prefix-based routing")
            return True

        except KeyboardInterrupt:
            print_error("Test interrupted by user")
            return False
        except Exception as e:
            print_error(f"Unexpected error during test: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(description="Test prefix-aware routing")
    parser.add_argument(
        "--base-url", default="", help="Base URL for the vLLM router service"
    )
    parser.add_argument(
        "--model", default="facebook/opt-125m", help="Model to use for testing"
    )
    parser.add_argument(
        "--num-requests-per-sample",
        type=int,
        default=3,
        help="Number of requests per sample",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument(
        "--debug", action="store_true", help="Enable debug mode (preserve temp files)"
    )
    parser.add_argument(
        "--chunk-size", type=int, default=128, help="Chunk size for prefixes"
    )

    args = parser.parse_args()

    # Create test instance
    test = PrefixAwareRoutingTest(
        base_url=args.base_url,
        model=args.model,
        num_requests_per_sample=args.num_requests_per_sample,
        verbose=args.verbose,
        debug=args.debug,
        chunk_size=args.chunk_size,
    )

    # Ensure cleanup happens
    try:
        success = test.run_test()
        sys.exit(0 if success else 1)
    finally:
        test.cleanup()


if __name__ == "__main__":
    main()
