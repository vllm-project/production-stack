import json
import tracemalloc
import types

import pytest
from prometheus_client import REGISTRY
from starlette.background import BackgroundTasks

from vllm_router.services.request_service.request import process_request
from vllm_router.stats.request_stats import RequestStatsMonitor, SingletonMeta

URL = "http://engine-1:8000"


@pytest.fixture
def monitor():
    SingletonMeta._instances.pop(RequestStatsMonitor, None)
    m = RequestStatsMonitor(sliding_window_size=10)
    yield m
    SingletonMeta._instances.pop(RequestStatsMonitor, None)


class _FakeContent:
    def __init__(self, chunks):
        self._chunks = chunks

    async def iter_any(self):
        for chunk in self._chunks:
            yield chunk


class _FakeBackendResponse:
    def __init__(self, chunks, content_type):
        self._response = types.SimpleNamespace(
            status=200,
            headers={"content-type": content_type},
            content=_FakeContent(chunks),
        )

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc):
        return False


class _RecordingCallbacks:
    def __init__(self):
        self.response_contents = []

    def post_request(self, request, response_content):
        self.response_contents.append(response_content)


def _fake_request(monitor, chunks, content_type, callbacks=None):
    state = types.SimpleNamespace(
        otel_enabled=False,
        semantic_cache_available=False,
        request_stats_monitor=monitor,
        aiohttp_client_wrapper=lambda: types.SimpleNamespace(
            request=lambda **kw: _FakeBackendResponse(chunks, content_type)
        ),
    )
    if callbacks is not None:
        # Mirrors --callbacks: the attribute only exists when configured.
        state.callbacks = callbacks
    return types.SimpleNamespace(
        method="POST",
        headers={"content-type": "application/json"},
        app=types.SimpleNamespace(state=state),
    )


async def _consume(request, body, background_tasks=None):
    received = []
    gen = process_request(
        request, body, URL, "req-1", "/v1/chat/completions", background_tasks
    )
    await anext(gen)  # headers and status
    async for chunk in gen:
        received.append(chunk)
    return b"".join(received)


@pytest.mark.asyncio
async def test_streamed_body_is_not_retained_without_post_request_callback(monitor):
    # Nothing reads the accumulated body of a streaming response unless a
    # post_request callback is configured, so the router must not hold a copy
    # of every in-flight stream in memory.
    chunk_size = 16 * 1024
    payload_size = 4 * 1024 * 1024
    # Allocated before tracing starts, so only the router's own allocations count.
    chunks = [bytes(chunk_size) for _ in range(payload_size // chunk_size)]
    request = _fake_request(monitor, chunks, "text/event-stream")
    body = json.dumps({"model": "test-model", "stream": True}).encode()

    tracemalloc.start()
    try:
        gen = process_request(request, body, URL, "req-1", "/v1/chat/completions", None)
        await anext(gen)
        async for _ in gen:
            pass  # a client that forwards and forgets each chunk
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert peak < payload_size // 4


@pytest.mark.asyncio
async def test_post_request_callback_receives_the_complete_streamed_body(monitor):
    chunks = [f'data: {{"token": {i}}}\n\n'.encode() for i in range(50)]
    callbacks = _RecordingCallbacks()
    request = _fake_request(monitor, chunks, "text/event-stream", callbacks)
    body = json.dumps({"model": "test-model", "stream": True}).encode()
    background_tasks = BackgroundTasks()

    await _consume(request, body, background_tasks)
    await background_tasks()

    assert callbacks.response_contents == [b"".join(chunks)]


@pytest.mark.asyncio
async def test_non_streaming_response_reports_token_usage(monitor):
    model = "token-usage-test-model"
    labels = {"server": URL, "model": model}
    before_in = REGISTRY.get_sample_value("vllm:input_tokens_total", labels) or 0
    before_out = REGISTRY.get_sample_value("vllm:output_tokens_total", labels) or 0
    response = b'{"usage": {"prompt_tokens": 11, "completion_tokens": 22}}'
    request = _fake_request(monitor, [response], "application/json")
    body = json.dumps({"model": model, "stream": False}).encode()

    await _consume(request, body)

    after_in = REGISTRY.get_sample_value("vllm:input_tokens_total", labels)
    after_out = REGISTRY.get_sample_value("vllm:output_tokens_total", labels)
    assert after_in - before_in == 11
    assert after_out - before_out == 22
