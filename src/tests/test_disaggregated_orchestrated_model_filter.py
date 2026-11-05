"""The orchestrated P/D flow only considers pods of the requested model."""

import asyncio
from types import SimpleNamespace
from unittest import mock

import vllm_router.services.request_service.request as request_module
from vllm_router.routers.routing_logic import DisaggregatedPrefillOrchestratedRouter


def _endpoint(url, label, model, sleep=False):
    return SimpleNamespace(url=url, model_label=label, model_names=[model], sleep=sleep)


ENDPOINTS = [
    _endpoint("http://a-prefill:8000", "prefill", "model-a"),
    _endpoint("http://a-decode:8000", "decode", "model-a"),
    _endpoint("http://b-prefill:8000", "prefill", "model-b"),
    _endpoint("http://b-decode:8000", "decode", "model-b"),
    _endpoint("http://a-prefill-asleep:8000", "prefill", "model-a", sleep=True),
]


def _run(model, body=None):
    seen = []
    router = DisaggregatedPrefillOrchestratedRouter.__new__(
        DisaggregatedPrefillOrchestratedRouter
    )

    def find_endpoints(endpoints):
        seen.extend(e.url for e in endpoints)
        raise ValueError("stop here")

    router._find_endpoints = find_endpoints
    request = SimpleNamespace(
        headers={}, app=SimpleNamespace(state=SimpleNamespace(router=router))
    )

    async def req_json():
        return body if body is not None else {"model": model, "prompt": "hi"}

    request.json = req_json
    discovery = SimpleNamespace(get_endpoint_info=lambda: ENDPOINTS)
    with mock.patch.object(request_module, "get_service_discovery", lambda: discovery):
        response = asyncio.run(
            request_module.route_orchestrated_disaggregated_request(
                request, "/v1/completions", None
            )
        )
    return seen, response


def test_only_endpoints_of_the_requested_model():
    seen, response = _run("model-b")
    assert seen == ["http://b-prefill:8000", "http://b-decode:8000"]
    assert response.status_code == 503


def test_sleeping_endpoints_skipped():
    seen, _ = _run("model-a")
    assert seen == ["http://a-prefill:8000", "http://a-decode:8000"]


def test_non_object_body_does_not_raise_in_the_filter():
    # A JSON body that is not an object: no model filter, the flow answers.
    seen, response = _run(None, body=["not", "an", "object"])
    assert seen == [e.url for e in ENDPOINTS]
    assert response.status_code == 503
