# Copyright 2024-2025 The vLLM Production Stack Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for the _build_debug_headers helper function."""

import unittest
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from unittest.mock import MagicMock

from vllm_router.services.request_service.request import _build_debug_headers


@dataclass
class MockEndpointInfo:
    url: str
    model_names: List[str]
    Id: str
    added_timestamp: float = 0.0
    model_label: str = ""
    sleep: bool = False
    pod_name: Optional[str] = None
    service_name: Optional[str] = None
    namespace: Optional[str] = None
    model_info: Dict = field(default_factory=dict)


class TestBuildDebugHeaders(unittest.TestCase):
    """Test the _build_debug_headers function."""

    def setUp(self):
        self.endpoints = [
            MockEndpointInfo(
                url="http://backend-1:8000",
                model_names=["llama"],
                Id="ep-1",
                pod_name="vllm-pod-abc",
            ),
            MockEndpointInfo(
                url="http://backend-2:8000",
                model_names=["llama"],
                Id="ep-2",
                pod_name="vllm-pod-def",
            ),
            MockEndpointInfo(
                url="http://backend-3:8000",
                model_names=["llama"],
                Id="ep-3",
                pod_name=None,
            ),
        ]

    def test_basic_debug_headers(self):
        """Test that basic debug headers are returned correctly."""
        headers = _build_debug_headers(
            "http://backend-1:8000", self.endpoints
        )
        self.assertEqual(headers["X-Backend-Server"], "http://backend-1:8000")
        self.assertEqual(headers["X-Backend-Id"], "ep-1")
        self.assertEqual(headers["X-Backend-Pod"], "vllm-pod-abc")

    def test_debug_headers_with_router(self):
        """Test that routing logic name is included when router is provided."""
        router = MagicMock()
        router.__class__.__name__ = "RoundRobinRouter"
        headers = _build_debug_headers(
            "http://backend-1:8000", self.endpoints, router=router
        )
        self.assertEqual(headers["X-Backend-Server"], "http://backend-1:8000")
        self.assertEqual(headers["X-Routing-Logic"], "RoundRobinRouter")

    def test_debug_headers_no_pod_name(self):
        """Test that X-Backend-Pod is omitted when pod_name is None."""
        headers = _build_debug_headers(
            "http://backend-3:8000", self.endpoints
        )
        self.assertEqual(headers["X-Backend-Server"], "http://backend-3:8000")
        self.assertEqual(headers["X-Backend-Id"], "ep-3")
        self.assertNotIn("X-Backend-Pod", headers)

    def test_debug_headers_unknown_server(self):
        """Test behavior when server_url doesn't match any endpoint."""
        headers = _build_debug_headers(
            "http://unknown:8000", self.endpoints
        )
        self.assertEqual(headers["X-Backend-Server"], "http://unknown:8000")
        self.assertNotIn("X-Backend-Id", headers)
        self.assertNotIn("X-Backend-Pod", headers)

    def test_debug_headers_without_router(self):
        """Test that X-Routing-Logic is omitted when router is None."""
        headers = _build_debug_headers(
            "http://backend-1:8000", self.endpoints, router=None
        )
        self.assertNotIn("X-Routing-Logic", headers)

    def test_debug_headers_second_endpoint(self):
        """Test that correct endpoint metadata is returned for second backend."""
        headers = _build_debug_headers(
            "http://backend-2:8000", self.endpoints
        )
        self.assertEqual(headers["X-Backend-Server"], "http://backend-2:8000")
        self.assertEqual(headers["X-Backend-Id"], "ep-2")
        self.assertEqual(headers["X-Backend-Pod"], "vllm-pod-def")


if __name__ == "__main__":
    unittest.main()
