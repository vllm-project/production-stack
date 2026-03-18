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

"""Tests for DisaggregatedPrefillRouter with conditional routing and round-robin."""

from typing import Dict

import pytest

from vllm_router.routers.routing_logic import DisaggregatedPrefillRouter
from vllm_router.utils import SingletonABCMeta


class EndpointInfo:
    def __init__(self, url: str, model_label: str):
        self.url = url
        self.model_label = model_label


class Request:
    def __init__(self, headers: Dict[str, str] = None):
        self.headers = headers or {}


@pytest.fixture(autouse=True)
def clear_singleton():
    """Clear DisaggregatedPrefillRouter singleton between tests."""
    if DisaggregatedPrefillRouter in SingletonABCMeta._instances:
        del SingletonABCMeta._instances[DisaggregatedPrefillRouter]
    yield
    if DisaggregatedPrefillRouter in SingletonABCMeta._instances:
        del SingletonABCMeta._instances[DisaggregatedPrefillRouter]


# --- Token estimation tests ---


def test_estimate_tokens_from_prompt_string():
    """char/4 heuristic for string prompts."""
    router = DisaggregatedPrefillRouter(["prefill"], ["decode"])
    # 400 chars -> 100 tokens
    request_json = {"prompt": "a" * 400}
    assert router._estimate_input_tokens(request_json) == 100


def test_estimate_tokens_from_prompt_token_ids():
    """Token ID list returns length directly."""
    router = DisaggregatedPrefillRouter(["prefill"], ["decode"])
    request_json = {"prompt": list(range(500))}
    assert router._estimate_input_tokens(request_json) == 500


def test_estimate_tokens_from_messages():
    """Chat completions messages use char/4 heuristic on concatenated content."""
    router = DisaggregatedPrefillRouter(["prefill"], ["decode"])
    request_json = {
        "messages": [
            {"role": "system", "content": "a" * 800},
            {"role": "user", "content": "b" * 1200},
        ]
    }
    # (800 + 1200) / 4 = 500
    assert router._estimate_input_tokens(request_json) == 500


def test_estimate_tokens_from_multimodal_messages():
    """Multimodal messages with list content extract text parts."""
    router = DisaggregatedPrefillRouter(["prefill"], ["decode"])
    request_json = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "x" * 400},
                    {"type": "image_url", "image_url": {"url": "http://example.com"}},
                ],
            }
        ]
    }
    assert router._estimate_input_tokens(request_json) == 100


def test_estimate_tokens_empty_request():
    """Empty request returns 0."""
    router = DisaggregatedPrefillRouter(["prefill"], ["decode"])
    assert router._estimate_input_tokens({}) == 0


# --- Conditional routing (should_disaggregate) tests ---


def test_should_disaggregate_threshold_zero_always_true():
    """Threshold 0 means always disaggregate (original behavior)."""
    router = DisaggregatedPrefillRouter(
        ["prefill"], ["decode"], routing_threshold=0
    )
    assert router.should_disaggregate({"prompt": "short"}) is True
    assert router.should_disaggregate({"prompt": "a" * 100000}) is True


def test_should_disaggregate_above_threshold():
    """Long input above threshold -> disaggregate."""
    router = DisaggregatedPrefillRouter(
        ["prefill"], ["decode"], routing_threshold=4096
    )
    # 20000 chars -> 5000 tokens > 4096
    assert router.should_disaggregate({"prompt": "a" * 20000}) is True


def test_should_disaggregate_below_threshold():
    """Short input below threshold -> don't disaggregate."""
    router = DisaggregatedPrefillRouter(
        ["prefill"], ["decode"], routing_threshold=4096
    )
    # 400 chars -> 100 tokens < 4096
    assert router.should_disaggregate({"prompt": "a" * 400}) is False


def test_should_disaggregate_at_threshold():
    """Input exactly at threshold -> don't disaggregate (must be strictly above)."""
    router = DisaggregatedPrefillRouter(
        ["prefill"], ["decode"], routing_threshold=1000
    )
    # 4000 chars -> 1000 tokens == 1000 threshold -> not above -> False
    assert router.should_disaggregate({"prompt": "a" * 4000}) is False


def test_should_disaggregate_negative_threshold():
    """Negative threshold treated same as 0 (always disaggregate)."""
    router = DisaggregatedPrefillRouter(
        ["prefill"], ["decode"], routing_threshold=-1
    )
    assert router.should_disaggregate({"prompt": "short"}) is True


# --- Round-robin endpoint selection tests ---


def test_round_robin_prefill_endpoints():
    """Prefill endpoints are selected in round-robin order."""
    router = DisaggregatedPrefillRouter(["prefill"], ["decode"])
    endpoints = [
        EndpointInfo("http://prefill1:8000", "prefill"),
        EndpointInfo("http://prefill2:8000", "prefill"),
        EndpointInfo("http://prefill3:8000", "prefill"),
    ]
    prefill_eps = [e for e in endpoints if e.model_label == "prefill"]

    urls = [router._select_prefill_endpoint(prefill_eps) for _ in range(6)]
    assert urls == [
        "http://prefill1:8000",
        "http://prefill2:8000",
        "http://prefill3:8000",
        "http://prefill1:8000",
        "http://prefill2:8000",
        "http://prefill3:8000",
    ]


def test_round_robin_decode_endpoints():
    """Decode endpoints are selected in round-robin order."""
    router = DisaggregatedPrefillRouter(["prefill"], ["decode"])
    endpoints = [
        EndpointInfo("http://decode1:8000", "decode"),
        EndpointInfo("http://decode2:8000", "decode"),
    ]
    decode_eps = [e for e in endpoints if e.model_label == "decode"]

    urls = [router._select_decode_endpoint(decode_eps) for _ in range(4)]
    assert urls == [
        "http://decode1:8000",
        "http://decode2:8000",
        "http://decode1:8000",
        "http://decode2:8000",
    ]


def test_round_robin_single_endpoint():
    """Single endpoint always returns the same URL."""
    router = DisaggregatedPrefillRouter(["prefill"], ["decode"])
    endpoints = [EndpointInfo("http://prefill1:8000", "prefill")]
    urls = [router._select_prefill_endpoint(endpoints) for _ in range(3)]
    assert urls == ["http://prefill1:8000"] * 3


def test_empty_prefill_endpoints_raises():
    """Empty prefill endpoints raises ValueError."""
    router = DisaggregatedPrefillRouter(["prefill"], ["decode"])
    with pytest.raises(ValueError, match="No prefill endpoints"):
        router._select_prefill_endpoint([])


def test_empty_decode_endpoints_raises():
    """Empty decode endpoints raises ValueError."""
    router = DisaggregatedPrefillRouter(["prefill"], ["decode"])
    with pytest.raises(ValueError, match="No decode endpoints"):
        router._select_decode_endpoint([])


# --- route_request integration tests ---


def test_route_request_prefill_round_robin():
    """route_request with is_prefill=True uses round-robin across prefill endpoints."""
    router = DisaggregatedPrefillRouter(["prefill"], ["decode"])
    endpoints = [
        EndpointInfo("http://prefill1:8000", "prefill"),
        EndpointInfo("http://prefill2:8000", "prefill"),
        EndpointInfo("http://decode1:8000", "decode"),
    ]
    req = Request()

    url1 = router.route_request(endpoints, {}, {}, req, {"max_tokens": 1})
    url2 = router.route_request(endpoints, {}, {}, req, {"max_tokens": 1})
    assert url1 == "http://prefill1:8000"
    assert url2 == "http://prefill2:8000"


def test_route_request_decode_round_robin():
    """route_request with is_prefill=False uses round-robin across decode endpoints."""
    router = DisaggregatedPrefillRouter(["prefill"], ["decode"])
    endpoints = [
        EndpointInfo("http://prefill1:8000", "prefill"),
        EndpointInfo("http://decode1:8000", "decode"),
        EndpointInfo("http://decode2:8000", "decode"),
    ]
    req = Request()

    url1 = router.route_request(endpoints, {}, {}, req, {"max_tokens": 256})
    url2 = router.route_request(endpoints, {}, {}, req, {"max_tokens": 256})
    assert url1 == "http://decode1:8000"
    assert url2 == "http://decode2:8000"


def test_route_request_backward_compatible():
    """With threshold=0 and single endpoints, behaves like original code."""
    router = DisaggregatedPrefillRouter(
        ["prefill"], ["decode"], routing_threshold=0
    )
    endpoints = [
        EndpointInfo("http://prefill1:8000", "prefill"),
        EndpointInfo("http://decode1:8000", "decode"),
    ]
    req = Request()

    # Prefill request
    url = router.route_request(endpoints, {}, {}, req, {"max_tokens": 1})
    assert url == "http://prefill1:8000"

    # Decode request
    url = router.route_request(endpoints, {}, {}, req, {"max_tokens": 256})
    assert url == "http://decode1:8000"
