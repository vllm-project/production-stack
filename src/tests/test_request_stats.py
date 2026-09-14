import json
import time
import types

import pytest
from fastapi import HTTPException

from vllm_router.services.request_service.request import process_request
from vllm_router.stats.request_stats import RequestStatsMonitor, SingletonMeta

URL = "http://engine-1:8000"


@pytest.fixture
def monitor():
    SingletonMeta._instances.pop(RequestStatsMonitor, None)
    m = RequestStatsMonitor(sliding_window_size=10)
    yield m
    SingletonMeta._instances.pop(RequestStatsMonitor, None)


def test_request_failing_during_prefill_releases_prefill_slot(monitor):
    # No on_request_response call => the request never left the prefill phase.
    now = time.time()
    monitor.on_new_request(URL, "req-1", now)
    monitor.on_request_complete(URL, "req-1", now + 1)

    stats = monitor.get_request_stats(now + 2)
    assert stats[URL].in_prefill_requests == 0
    assert stats[URL].in_decoding_requests == 0
    assert stats[URL].finished_requests == 1


def test_on_request_complete_is_idempotent(monitor):
    # Failover / the finally-block can fire on_request_complete twice for one request.
    now = time.time()
    monitor.on_new_request(URL, "req-1", now)
    monitor.on_request_response(URL, "req-1", now + 0.5)
    monitor.on_request_complete(URL, "req-1", now + 1)
    monitor.on_request_complete(URL, "req-1", now + 1)

    stats = monitor.get_request_stats(now + 2)
    assert stats[URL].finished_requests == 1
    assert stats[URL].in_decoding_requests == 0


def test_completed_request_releases_per_request_bookkeeping(monitor):
    # Per-request entries must not accumulate for the life of the process.
    now = time.time()
    monitor.on_new_request(URL, "req-1", now)
    monitor.on_request_response(URL, "req-1", now + 0.5)
    monitor.on_request_complete(URL, "req-1", now + 1)

    assert monitor.request_start_time == {}
    assert monitor.first_token_time == {}


class _RaisingRequestCM:
    async def __aenter__(self):
        raise ConnectionError("backend down")

    async def __aexit__(self, *exc):
        return False


class _FakeContent:
    def __init__(self, chunks):
        self._chunks = chunks

    async def iter_any(self):
        for chunk in self._chunks:
            yield chunk


class _OkRequestCM:
    async def __aenter__(self):
        return types.SimpleNamespace(
            status=200,
            headers={"content-type": "application/json"},
            content=_FakeContent([b'{"usage": {}}']),
        )

    async def __aexit__(self, *exc):
        return False


def _fake_request(monitor, cm_factory):
    state = types.SimpleNamespace(
        otel_enabled=False,
        semantic_cache_available=False,
        request_stats_monitor=monitor,
        aiohttp_client_wrapper=lambda: types.SimpleNamespace(
            request=lambda **kw: cm_factory()
        ),
    )
    return types.SimpleNamespace(
        method="POST",
        headers={"content-type": "application/json"},
        app=types.SimpleNamespace(state=state),
    )


@pytest.mark.asyncio
async def test_process_request_releases_slot_when_backend_errors(monitor):
    # Backend failure must still release the slot, or load-aware / priority
    # routing sees the engine as permanently loaded.
    request = _fake_request(monitor, _RaisingRequestCM)
    body = json.dumps({"model": "test-model", "stream": False}).encode()

    gen = process_request(request, body, URL, "req-1", "/v1/chat/completions", None)
    with pytest.raises(ConnectionError):
        async for _ in gen:
            pass

    stats = monitor.get_request_stats(time.time())
    assert stats[URL].in_prefill_requests == 0
    assert stats[URL].in_decoding_requests == 0


@pytest.mark.asyncio
async def test_process_request_releases_slot_on_unparsable_body(monitor):
    # on_new_request runs before the body is parsed; a non-JSON body must still
    # release the slot and surface as a 400.
    request = _fake_request(monitor, _OkRequestCM)  # backend never reached
    gen = process_request(
        request, b"not json", URL, "req-1", "/v1/chat/completions", None
    )

    with pytest.raises(HTTPException) as exc:
        async for _ in gen:
            pass
    assert exc.value.status_code == 400

    stats = monitor.get_request_stats(time.time())
    assert stats[URL].in_prefill_requests == 0


@pytest.mark.asyncio
async def test_process_request_balances_counters_on_success(monitor):
    request = _fake_request(monitor, _OkRequestCM)
    body = json.dumps({"model": "test-model", "stream": False}).encode()

    gen = process_request(request, body, URL, "req-1", "/v1/chat/completions", None)
    async for _ in gen:
        pass

    stats = monitor.get_request_stats(time.time())
    assert stats[URL].in_prefill_requests == 0
    assert stats[URL].in_decoding_requests == 0
    assert stats[URL].finished_requests == 1
    assert monitor.request_start_time == {}
