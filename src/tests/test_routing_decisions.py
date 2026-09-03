"""Routing decision metadata stays compatible with existing URL-string callers."""

import copy
import pickle
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from vllm_router.routers.routing_logic import (
    DisaggregatedPrefillOrchestratedRouter,
    DisaggregatedPrefillRouter,
    RoutingDecision,
    cleanup_routing_logic,
)
from vllm_router.services.request_service.request import _record_backend_selection


def test_routing_decision_is_a_string_with_bounded_metadata():
    decision = RoutingDecision(
        "http://backend.internal:8000",
        algorithm="unbounded-algorithm",
        decision="unbounded-decision",
        reason="exception: secret request data",
    )

    assert isinstance(decision, str)
    assert decision == "http://backend.internal:8000"
    assert decision.algorithm == "unknown"
    assert decision.decision == "unknown"
    assert decision.reason == "unknown"


def test_routing_decision_has_no_mutable_instance_dictionary():
    decision = RoutingDecision(
        "http://backend.internal:8000",
        algorithm="roundrobin",
        decision="primary",
        reason="round_robin",
    )

    assert not hasattr(decision, "__dict__")
    with pytest.raises(AttributeError, match="immutable"):
        decision.algorithm = "priority"


@pytest.mark.parametrize("attribute", ["algorithm", "decision", "reason"])
def test_routing_decision_metadata_cannot_be_deleted(attribute):
    decision = RoutingDecision(
        "http://backend.internal:8000",
        algorithm="roundrobin",
        decision="primary",
        reason="round_robin",
    )
    original_metadata = (decision.algorithm, decision.decision, decision.reason)

    with pytest.raises(AttributeError, match="immutable"):
        delattr(decision, attribute)

    assert (decision.algorithm, decision.decision, decision.reason) == original_metadata


@pytest.mark.parametrize("attribute", ["algorithm", "decision", "reason"])
def test_routing_decision_metadata_resists_object_setattr(attribute):
    decision = RoutingDecision(
        "http://backend.internal:8000",
        algorithm="roundrobin",
        decision="primary",
        reason="round_robin",
    )
    original_metadata = (decision.algorithm, decision.decision, decision.reason)

    with pytest.raises(AttributeError):
        object.__setattr__(decision, attribute, "unknown")

    assert (decision.algorithm, decision.decision, decision.reason) == original_metadata


@pytest.mark.parametrize("attribute", ["algorithm", "decision", "reason"])
def test_routing_decision_metadata_resists_object_delattr(attribute):
    decision = RoutingDecision(
        "http://backend.internal:8000",
        algorithm="roundrobin",
        decision="primary",
        reason="round_robin",
    )
    original_metadata = (decision.algorithm, decision.decision, decision.reason)

    with pytest.raises(AttributeError):
        object.__delattr__(decision, attribute)

    assert (decision.algorithm, decision.decision, decision.reason) == original_metadata


@pytest.mark.parametrize(
    "round_trip",
    [copy.copy, copy.deepcopy, lambda value: pickle.loads(pickle.dumps(value))],
    ids=["copy", "deepcopy", "pickle"],
)
def test_routing_decision_round_trips_value_and_metadata(round_trip):
    decision = RoutingDecision(
        "http://backend.internal:8000",
        algorithm="loadaware",
        decision="fallback",
        reason="no_live_holder",
    )

    restored = round_trip(decision)

    assert type(restored) is RoutingDecision
    assert restored == decision
    assert (restored.algorithm, restored.decision, restored.reason) == (
        "loadaware",
        "fallback",
        "no_live_holder",
    )


def test_backend_selection_records_only_bounded_decision_dimensions():
    selection = RoutingDecision(
        "http://unidentified.internal:8000",
        algorithm="roundrobin",
        decision="primary",
        reason="round_robin",
    )
    endpoint = SimpleNamespace(url=str(selection), Id=None)

    with patch(
        "vllm_router.services.request_service.request.record_routing_decision"
    ) as metric_mock:
        _record_backend_selection(selection, [endpoint])

    metric_mock.assert_called_once_with(
        algorithm="roundrobin",
        decision="primary",
        reason="round_robin",
    )


def test_disaggregated_prefill_router_labels_prefill_and_decode():
    cleanup_routing_logic()
    router = DisaggregatedPrefillRouter(["prefill"], ["decode"])
    endpoints = [
        SimpleNamespace(url="http://prefill", model_label="prefill"),
        SimpleNamespace(url="http://decode", model_label="decode"),
    ]

    prefill = router.route_request(endpoints, {}, {}, None, {"max_tokens": 1})
    decode = router.route_request(endpoints, {}, {}, None, {"max_tokens": 2})

    assert (prefill.algorithm, prefill.decision, prefill.reason) == (
        "disaggregated_prefill",
        "primary",
        "prefill",
    )
    assert (decode.algorithm, decode.decision, decode.reason) == (
        "disaggregated_prefill",
        "primary",
        "decode",
    )
    cleanup_routing_logic()


@pytest.mark.asyncio
async def test_orchestrated_router_route_request_has_prefill_metadata():
    cleanup_routing_logic()
    router = DisaggregatedPrefillOrchestratedRouter(["prefill"], ["decode"])
    selected = await router.route_request(
        [
            SimpleNamespace(url="http://prefill", model_label="prefill"),
            SimpleNamespace(url="http://decode", model_label="decode"),
        ],
        {},
        {},
        None,
        {},
    )

    assert selected == "http://prefill"
    assert (selected.algorithm, selected.decision, selected.reason) == (
        "disaggregated_prefill_orchestrated",
        "primary",
        "prefill",
    )
    cleanup_routing_logic()
