"""Unit tests for route_sleep_wakeup_request's /reset_prefix_cache support.

route_sleep_wakeup_request already backs /sleep, /wake_up, /is_sleeping.
These tests cover two things: the new /reset_prefix_cache endpoint relays
vLLM's real response body (unlike /sleep and /wake_up, whose upstream body
is always empty and safe to ignore), and that existing /sleep behavior is
provably unchanged by that change.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vllm_router.services.request_service.request import route_sleep_wakeup_request
from vllm_router.utils import SingletonABCMeta


class EndpointInfo:
    def __init__(self, id_, url, pod_name):
        self.Id = id_
        self.url = url
        self.pod_name = pod_name


@pytest.fixture(autouse=True)
def cleanup_singletons():
    yield
    for cls in list(SingletonABCMeta._instances.keys()):
        del SingletonABCMeta._instances[cls]


def _build_request(query_params, body=b""):
    request = MagicMock()
    request.headers = {}
    request.query_params = query_params
    request.body = AsyncMock(return_value=body)
    return request


def _mock_aiohttp_session(response_status, response_json=None):
    """Build a mock aiohttp.ClientSession usable both as
    `async with aiohttp.ClientSession() as client:` and, on the returned
    client, `async with client.post(...) as response:`.
    """
    mock_response = MagicMock()
    mock_response.status = response_status
    mock_response.raise_for_status = MagicMock()
    mock_response.json = AsyncMock(return_value=response_json)

    mock_post_cm = MagicMock()
    mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_post_cm.__aexit__ = AsyncMock(return_value=False)

    mock_client = MagicMock()
    mock_client.post = MagicMock(return_value=mock_post_cm)

    mock_session_cm = MagicMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_session_cm.__aexit__ = AsyncMock(return_value=False)

    return mock_session_cm, mock_client, mock_response


@pytest.mark.asyncio
@pytest.mark.parametrize("request_body", [b"", b"{}"])
async def test_reset_prefix_cache_relays_real_response_body(request_body):
    """/reset_prefix_cache's real vLLM response body (`{"success": bool}`)
    must be relayed to the caller, since `success: false` is a legitimate,
    meaningful outcome (blocks still held) -- not swallowed into the old
    canned `{"status": "success"}`.

    Parameterized over an empty and a non-empty request body: a real
    /reset_prefix_cache caller never sends a body, but nothing stops one
    from doing so (e.g. a client that always attaches `{}`), and this
    endpoint's relay logic must not depend on which branch that puts it in.
    """
    endpoint_info = EndpointInfo("X", "http://engine-x:8000", "pod-x")
    service_discovery = MagicMock()
    service_discovery.get_endpoint_info.return_value = [endpoint_info]

    mock_session_cm, mock_client, mock_response = _mock_aiohttp_session(
        response_status=200, response_json={"success": False}
    )

    request = _build_request(
        {"id": "X", "reset_external": "true"}, body=request_body
    )

    with (
        patch(
            "vllm_router.services.request_service.request.get_service_discovery",
            return_value=service_discovery,
        ),
        patch(
            "vllm_router.services.request_service.request.aiohttp.ClientSession",
            return_value=mock_session_cm,
        ),
    ):
        response = await route_sleep_wakeup_request(
            request, "/reset_prefix_cache", MagicMock()
        )

    # The real vLLM body was relayed, not the canned status.
    assert json.loads(response.body) == {"success": False}

    # Correct upstream URL and forwarded params (id excluded).
    call_args = mock_client.post.call_args
    assert call_args.args[0] == "http://engine-x:8000/reset_prefix_cache"
    assert call_args.kwargs["params"] == {"reset_external": "true"}
    mock_response.json.assert_awaited_once()


@pytest.mark.asyncio
async def test_sleep_still_returns_canned_status_unaffected():
    """Regression: /sleep's existing behavior (canned {"status": "success"},
    ignoring the empty upstream body) must be unchanged by the
    /reset_prefix_cache relay logic added alongside it.
    """
    endpoint_info = EndpointInfo("X", "http://engine-x:8000", "pod-x")
    service_discovery = MagicMock()
    service_discovery.get_endpoint_info.return_value = [endpoint_info]
    service_discovery.add_sleep_label = MagicMock()

    mock_session_cm, mock_client, mock_response = _mock_aiohttp_session(
        response_status=200, response_json=None
    )

    request = _build_request({"id": "X", "level": "2"})

    with (
        patch(
            "vllm_router.services.request_service.request.get_service_discovery",
            return_value=service_discovery,
        ),
        patch(
            "vllm_router.services.request_service.request.aiohttp.ClientSession",
            return_value=mock_session_cm,
        ),
    ):
        response = await route_sleep_wakeup_request(request, "/sleep", MagicMock())

    assert json.loads(response.body) == {"status": "success"}
    # The relay logic must never even attempt to parse /sleep's body.
    mock_response.json.assert_not_called()
    service_discovery.add_sleep_label.assert_called_once_with("pod-x")
