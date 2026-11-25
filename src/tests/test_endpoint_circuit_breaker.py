"""The circuit breaker of the orchestrated P/D router: an endpoint that keeps
failing is skipped for a cooldown, then tried again."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from vllm_router.routers.routing_logic import (
    DisaggregatedPrefillOrchestratedRouter,
    EndpointCircuitBreaker,
    RoutingLogic,
    cleanup_routing_logic,
    initialize_routing_logic,
)

A, B = (SimpleNamespace(url=url) for url in ("http://a", "http://b"))


@pytest.fixture
def clock():
    """A controllable time.monotonic() for the circuit breaker."""
    now = SimpleNamespace(value=1000.0)
    with patch("vllm_router.routers.routing_logic.time.monotonic", lambda: now.value):
        yield now


@pytest.fixture(autouse=True)
def clean_router_singletons():
    cleanup_routing_logic()
    yield
    cleanup_routing_logic()


def test_opens_after_threshold_consecutive_failures(clock):
    breaker = EndpointCircuitBreaker(failure_threshold=3, cooldown_seconds=30)

    breaker.record_failure(A.url)
    breaker.record_failure(A.url)
    assert breaker.available([A, B]) == [A, B]

    breaker.record_failure(A.url)
    assert breaker.available([A, B]) == [B]


def test_success_resets_the_failure_count(clock):
    breaker = EndpointCircuitBreaker(failure_threshold=3, cooldown_seconds=30)

    breaker.record_failure(A.url)
    breaker.record_failure(A.url)
    breaker.record_success(A.url)
    breaker.record_failure(A.url)
    breaker.record_failure(A.url)

    assert breaker.available([A, B]) == [A, B]


def test_endpoint_is_tried_again_after_the_cooldown(clock):
    breaker = EndpointCircuitBreaker(failure_threshold=2, cooldown_seconds=30)
    breaker.record_failure(A.url)
    breaker.record_failure(A.url)

    clock.value += 29
    assert breaker.available([A, B]) == [B]
    clock.value += 1
    assert breaker.available([A, B]) == [A, B]

    # A single failure opens it for another cooldown...
    breaker.record_failure(A.url)
    assert breaker.available([A, B]) == [B]

    # ...and a success closes it.
    clock.value += 30
    breaker.record_success(A.url)
    breaker.record_failure(A.url)
    assert breaker.available([A, B]) == [A, B]


def test_all_endpoints_open_falls_back_to_the_first_to_recover(clock):
    breaker = EndpointCircuitBreaker(failure_threshold=1, cooldown_seconds=30)
    breaker.record_failure(B.url)
    clock.value += 10
    breaker.record_failure(A.url)

    assert breaker.available([A, B]) == [B]


def test_disabled_by_default(clock):
    breaker = EndpointCircuitBreaker()

    for _ in range(10):
        breaker.record_failure(A.url)

    assert breaker.available([A, B]) == [A, B]


def test_endpoints_that_stopped_failing_are_forgotten(clock):
    breaker = EndpointCircuitBreaker(failure_threshold=2, cooldown_seconds=30)
    breaker.record_failure(A.url)

    clock.value += 601
    breaker.record_failure(B.url)
    breaker.record_failure(A.url)

    assert breaker.available([A, B]) == [A, B]


def test_router_skips_open_endpoints_for_both_roles(clock):
    router = DisaggregatedPrefillOrchestratedRouter(["prefill"], ["decode"])
    router.circuit_breaker = EndpointCircuitBreaker(failure_threshold=1)
    router.circuit_breaker.record_failure(A.url)

    assert [router.select_prefill_endpoint([A, B]) for _ in range(3)] == [B, B, B]
    assert [router.select_decode_endpoint([A, B]) for _ in range(3)] == [B, B, B]

    clock.value += 30
    assert {router.select_prefill_endpoint([A, B]).url for _ in range(2)} == {
        A.url,
        B.url,
    }


def test_initialize_routing_logic_configures_the_circuit_breaker():
    router = initialize_routing_logic(
        RoutingLogic.DISAGGREGATED_PREFILL_ORCHESTRATED,
        prefill_model_labels=["prefill"],
        decode_model_labels=["decode"],
        pd_endpoint_failure_threshold=5,
        pd_endpoint_cooldown_seconds=12.5,
    )

    assert router.circuit_breaker.failure_threshold == 5
    assert router.circuit_breaker.cooldown_seconds == 12.5
