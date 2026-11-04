import json
import logging
from itertools import permutations
from unittest.mock import MagicMock

import pytest

from vllm_router.routers.main_router import show_models
from vllm_router.service_discovery import EndpointInfo, ModelInfo


def _build_request():
    request = MagicMock()
    request.app.state = MagicMock()
    request.app.state.external_provider_registry = None
    return request


def _build_endpoint(model_payload, *additional_payloads):
    payloads = [model_payload, *additional_payloads]
    model_ids = [payload["id"] for payload in payloads]
    return EndpointInfo(
        url="http://engine",
        model_names=model_ids,
        Id="engine-1",
        added_timestamp=0.0,
        model_label=model_ids[0],
        sleep=False,
        model_info={
            payload["id"]: ModelInfo.from_dict(payload) for payload in payloads
        },
    )


def test_model_info_preserves_extra_fields():
    payload = {
        "id": "test-model",
        "object": "model",
        "created": 123,
        "owned_by": "vllm",
        "root": "models/test-model",
        "parent": None,
        "max_model_len": 8192,
        "permission": [{"id": "perm-1", "allow_sampling": True}],
    }

    model_info = ModelInfo.from_dict(payload)

    assert model_info.extra_fields == {
        "max_model_len": 8192,
        "permission": [{"id": "perm-1", "allow_sampling": True}],
    }
    assert model_info.to_dict() == payload


@pytest.mark.asyncio
async def test_show_models_returns_full_backend_model_payload(monkeypatch):
    payload = {
        "id": "rich-model",
        "object": "model",
        "created": 1774275193,
        "owned_by": "vllm",
        "root": "models/rich-model",
        "parent": None,
        "max_model_len": 262144,
        "permission": [
            {
                "id": "modelperm-1",
                "object": "model_permission",
                "allow_sampling": True,
                "allow_logprobs": True,
            }
        ],
    }

    monkeypatch.setattr(
        "vllm_router.routers.main_router.get_service_discovery",
        lambda: MagicMock(get_endpoint_info=lambda: [_build_endpoint(payload)]),
    )

    response = await show_models(_build_request())

    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["data"] == [payload]


@pytest.mark.asyncio
async def test_show_models_does_not_warn_for_preserved_backend_fields(
    monkeypatch, caplog
):
    payload = {
        "id": "rich-model",
        "object": "model",
        "created": 1774275193,
        "owned_by": "vllm",
        "root": "models/rich-model",
        "parent": None,
        "max_model_len": 262144,
        "permission": [
            {
                "id": "modelperm-1",
                "object": "model_permission",
                "allow_sampling": True,
                "allow_logprobs": True,
            }
        ],
    }

    monkeypatch.setattr(
        "vllm_router.routers.main_router.get_service_discovery",
        lambda: MagicMock(get_endpoint_info=lambda: [_build_endpoint(payload)]),
    )

    with caplog.at_level(logging.WARNING, logger="vllm_router.protocols"):
        response = await show_models(_build_request())

    assert response.status_code == 200
    assert "ignored" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint_order", list(permutations(range(3))))
@pytest.mark.parametrize("reverse_model_order", [False, True])
@pytest.mark.parametrize("reverse_provider_order", [False, True])
async def test_show_models_order_is_independent_of_discovery(
    monkeypatch, endpoint_order, reverse_model_order, reverse_provider_order
):
    payloads = {
        model_id: {
            "id": model_id,
            "object": "model",
            "created": 123,
            "owned_by": "vllm",
            "root": f"models/{model_id}",
            "parent": None,
            "max_model_len": 262144,
            "permission": [{"id": "perm-1", "allow_sampling": True}],
        }
        for model_id in ["70 - Zeta", "alias-zeta", "2 - Beta", "01 - Alpha"]
    }
    groups = [
        ["70 - Zeta", "alias-zeta"],
        ["2 - Beta", "01 - Alpha"],
        ["2 - Beta"],  # Another backend serving the same model.
    ]
    endpoints = [
        _build_endpoint(
            *(
                payloads[model_id]
                for model_id in (
                    list(reversed(groups[index]))
                    if reverse_model_order
                    else groups[index]
                )
            )
        )
        for index in endpoint_order
    ]
    discovery_order = [list(endpoint.model_info) for endpoint in endpoints]
    monkeypatch.setattr(
        "vllm_router.routers.main_router.get_service_discovery",
        lambda: MagicMock(get_endpoint_info=lambda: endpoints),
    )
    request = _build_request()
    registry = MagicMock()
    provider_ids = ["10 - Delta", "alias-z", "2 - Beta"]
    registry.get_all_external_model_ids.return_value = (
        list(reversed(provider_ids)) if reverse_provider_order else provider_ids
    )
    registry.get_provider_name.return_value = "test-provider"
    request.app.state.external_provider_registry = registry

    response = await show_models(request)

    cards = json.loads(response.body)["data"]
    assert [card["id"] for card in cards] == [
        "01 - Alpha",
        "2 - Beta",
        "10 - Delta",
        "70 - Zeta",
        "alias-z",
        "alias-zeta",
    ]
    by_id = {card["id"]: card for card in cards}
    for model_id, payload in payloads.items():
        assert by_id[model_id] == payload
    assert by_id["10 - Delta"]["owned_by"] == "test-provider"
    assert by_id["alias-z"]["owned_by"] == "test-provider"
    assert [list(endpoint.model_info) for endpoint in endpoints] == discovery_order


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse_order", [False, True])
async def test_show_models_numeric_prefixes_and_case_ties(monkeypatch, reverse_order):
    expected_ids = [
        "01 - Alpha",
        "02 - Beta",
        "2 - Beta",
        "2 - beta",
        "10 - Delta",
        "70 - Zeta",
        "Alias",
        "alias",
        "alias-z",
        "alias-zeta",
        "release-10",
        "release-2",
    ]
    model_ids = list(reversed(expected_ids)) if reverse_order else expected_ids
    endpoint = _build_endpoint(*({"id": model_id} for model_id in model_ids))
    monkeypatch.setattr(
        "vllm_router.routers.main_router.get_service_discovery",
        lambda: MagicMock(get_endpoint_info=lambda: [endpoint]),
    )

    response = await show_models(_build_request())

    assert [card["id"] for card in json.loads(response.body)["data"]] == expected_ids


@pytest.mark.asyncio
async def test_show_models_empty_catalog(monkeypatch):
    monkeypatch.setattr(
        "vllm_router.routers.main_router.get_service_discovery",
        lambda: MagicMock(get_endpoint_info=lambda: []),
    )

    response = await show_models(_build_request())

    assert json.loads(response.body) == {"object": "list", "data": []}
