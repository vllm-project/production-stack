"""Unit tests for route_sleep_wakeup_request's response-relay behavior.

route_sleep_wakeup_request backs /sleep, /wake_up, /is_sleeping, and
/reset_prefix_cache. After every POST it now always tries to parse and
relay the real upstream JSON body, falling back to the old canned
{"status": "success"} only when parsing fails (an empty body, as /sleep
and /wake_up send). These tests cover that generic behavior relaying
/reset_prefix_cache's real body, and that /sleep's existing behavior is
provably unchanged.
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


def _mock_aiohttp_session(response_status, response_json=None, json_raises=False):
    """Build a mock aiohttp.ClientSession usable both as
    `async with aiohttp.ClientSession() as client:` and, on the returned
    client, `async with client.post(...) as response:`.

    json_raises=True simulates a real empty-body response, where aiohttp's
    response.json() raises rather than returning None.
    """
    mock_response = MagicMock()
    mock_response.status = response_status
    mock_response.raise_for_status = MagicMock()
    if json_raises:
        mock_response.json = AsyncMock(
            side_effect=json.JSONDecodeError("Expecting value", "", 0)
        )
    else:
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
    """Regression: /sleep's existing behavior (canned {"status": "success"})
    must be unchanged by the generic relay logic. /sleep's real upstream
    response body is empty, so response.json() raises (simulated here) and
    the code must fall back to the canned status, not propagate the error.
    """
    endpoint_info = EndpointInfo("X", "http://engine-x:8000", "pod-x")
    service_discovery = MagicMock()
    service_discovery.get_endpoint_info.return_value = [endpoint_info]
    service_discovery.add_sleep_label = MagicMock()

    mock_session_cm, mock_client, mock_response = _mock_aiohttp_session(
        response_status=200, json_raises=True
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
    # The relay logic does attempt to parse /sleep's body now (generic,
    # unconditional) -- it must just fail gracefully and fall back.
    mock_response.json.assert_awaited_once()
    service_discovery.add_sleep_label.assert_called_once_with("pod-x")
