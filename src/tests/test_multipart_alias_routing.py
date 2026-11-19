"""Tests for alias resolution on multipart routes (#1143).

/v1/audio/translations and /v1/images/edits go through
route_multipart_request (raw body passthrough), while
/v1/audio/transcriptions parses typed fields. When the client sends a
configured alias, all of them must route by — and forward — the canonical
model, preserving uploaded files and other form fields.
"""

import types
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from vllm_router.routers.routing_logic import RoundRobinRouter
from vllm_router.services.request_service import request as request_module
from vllm_router.utils import SingletonABCMeta


class EndpointInfo:
    def __init__(self, url, model_names=None, sleep=False, Id=None):
        self.url = url
        self.model_names = model_names or ["openai/whisper-tiny"]
        self.sleep = sleep
        self.Id = Id


ENDPOINTS = [EndpointInfo(url="http://asr-engine")]
ALIASES = {"audio-alias": "openai/whisper-tiny"}


@pytest.fixture(autouse=True)
def cleanup_singletons():
    yield
    for cls in list(SingletonABCMeta._instances.keys()):
        del SingletonABCMeta._instances[cls]


class _Upload:
    """Stand-in for starlette's UploadFile."""

    def __init__(self, content, filename, content_type):
        self._content = content
        self.filename = filename
        self.content_type = content_type

    async def read(self):
        return self._content


class _Form:
    def __init__(self, fields):
        self._fields = fields  # list of (key, str | _Upload)

    def _last(self, key):
        value = None
        found = False
        for k, v in self._fields:
            if k == key:
                value = v
                found = True
        if not found:
            raise KeyError(key)
        return value

    def get(self, key, default=None):
        try:
            return self._last(key)
        except KeyError:
            return default

    def __getitem__(self, key):
        return self._last(key)

    def multi_items(self):
        return list(self._fields)


class _Request:
    def __init__(self, form):
        self._form = form
        self.headers = {}
        self.app = MagicMock()

    async def body(self):
        return b"raw-bytes"

    async def form(self):
        return self._form


def _discovery(aliases):
    sd = MagicMock()
    sd.get_endpoint_info.return_value = ENDPOINTS
    sd.aliases = aliases
    return sd


def _form_pairs(form_data):
    assert isinstance(form_data, aiohttp.FormData)
    # aiohttp 3.14 stores (content_disposition, content_type, value) triples.
    return [(cd["name"], value) for cd, _ct, value in form_data._fields]


@pytest.mark.asyncio
async def test_route_multipart_alias_routes_canonical_and_preserves_fields():
    proxy = AsyncMock()
    form = _Form(
        [
            ("model", "audio-alias"),
            ("language", "en"),
            ("file", _Upload(b"abc", "speech.wav", "audio/wav")),
        ]
    )
    with (
        patch.object(
            request_module, "get_service_discovery", return_value=_discovery(ALIASES)
        ),
        patch.object(request_module, "proxy_multipart_request", proxy),
    ):
        await request_module.route_multipart_request(
            _Request(form), "/v1/audio/translations", None
        )

    forwarded_model = proxy.call_args[0][1]
    assert forwarded_model == "openai/whisper-tiny"

    rebuilt = proxy.call_args[0][0]
    pairs = _form_pairs(rebuilt)
    assert ("model", "openai/whisper-tiny") in pairs
    assert ("language", "en") in pairs
    assert ("file", b"abc") in pairs


@pytest.mark.asyncio
async def test_route_multipart_without_alias_forwards_raw_body():
    proxy = AsyncMock()
    form = _Form([("model", "openai/whisper-tiny")])
    with (
        patch.object(
            request_module, "get_service_discovery", return_value=_discovery(None)
        ),
        patch.object(request_module, "proxy_multipart_request", proxy),
    ):
        await request_module.route_multipart_request(
            _Request(form), "/v1/images/edits", None
        )

    assert proxy.call_args[0][0] == b"raw-bytes"
    assert proxy.call_args[0][1] == "openai/whisper-tiny"


@pytest.mark.asyncio
async def test_route_multipart_repeated_model_fields_are_normalized():
    """starlette routes by the last value; an aiohttp backend reads the first."""
    proxy = AsyncMock()
    form = _Form(
        [
            ("model", "audio-alias"),
            ("model", "openai/whisper-tiny"),
        ]
    )
    with (
        patch.object(
            request_module, "get_service_discovery", return_value=_discovery(ALIASES)
        ),
        patch.object(request_module, "proxy_multipart_request", proxy),
    ):
        await request_module.route_multipart_request(
            _Request(form), "/v1/images/edits", None
        )

    assert proxy.call_args[0][1] == "openai/whisper-tiny"
    pairs = _form_pairs(proxy.call_args[0][0])
    assert pairs.count(("model", "openai/whisper-tiny")) == 2


@pytest.mark.asyncio
async def test_route_multipart_resolves_empty_string_alias_like_json_path():
    proxy = AsyncMock()
    form = _Form([("model", "")])
    with (
        patch.object(
            request_module,
            "get_service_discovery",
            return_value=_discovery({"": "openai/whisper-tiny"}),
        ),
        patch.object(request_module, "proxy_multipart_request", proxy),
    ):
        await request_module.route_multipart_request(
            _Request(form), "/v1/audio/translations", None
        )

    assert proxy.call_args[0][1] == "openai/whisper-tiny"
    assert ("model", "openai/whisper-tiny") in _form_pairs(proxy.call_args[0][0])


@pytest.mark.asyncio
async def test_route_multipart_alias_without_file_keeps_multipart_media_type():
    proxy = AsyncMock()
    form = _Form(
        [
            ("model", "audio-alias"),
            ("prompt", "hi"),
        ]
    )
    with (
        patch.object(
            request_module, "get_service_discovery", return_value=_discovery(ALIASES)
        ),
        patch.object(request_module, "proxy_multipart_request", proxy),
    ):
        await request_module.route_multipart_request(
            _Request(form), "/v1/audio/translations", None
        )

    content_type = proxy.call_args[0][0]().headers["Content-Type"]
    assert content_type.startswith("multipart/form-data")


@pytest.mark.asyncio
async def test_route_multipart_alias_to_empty_target_forwards_empty_model():
    """An explicitly empty canonical target must not fall back to the alias."""
    proxy = AsyncMock()
    form = _Form([("model", "voice")])
    with (
        patch.object(
            request_module,
            "get_service_discovery",
            return_value=_discovery({"voice": ""}),
        ),
        patch.object(request_module, "proxy_multipart_request", proxy),
    ):
        await request_module.route_multipart_request(
            _Request(form), "/v1/audio/translations", None
        )

    assert proxy.call_args[0][1] == ""


@pytest.mark.asyncio
async def test_transcriptions_alias_forwards_canonical_and_fields():
    proxy = AsyncMock()
    form = _Form(
        [
            ("model", "audio-alias"),
            ("prompt", "hi"),
            ("file", _Upload(b"wav-bytes", "speech.wav", "audio/wav")),
        ]
    )
    with (
        patch.object(
            request_module, "get_service_discovery", return_value=_discovery(ALIASES)
        ),
        patch.object(request_module, "proxy_multipart_request", proxy),
    ):
        await request_module.route_general_transcriptions(
            _Request(form), "/v1/audio/transcriptions", None
        )

    assert proxy.call_args[0][1] == "openai/whisper-tiny"
    pairs = _form_pairs(proxy.call_args[0][0])
    assert ("model", "openai/whisper-tiny") in pairs
    assert ("prompt", "hi") in pairs
    assert ("file", b"wav-bytes") in pairs


@pytest.mark.asyncio
async def test_proxy_multipart_unresolved_alias_returns_404():
    """Documents the bug: proxy itself never resolves aliases."""
    state = MagicMock()
    state.router = RoundRobinRouter()
    state.engine_stats_scraper.get_engine_stats.return_value = {}
    state.request_stats_monitor.get_request_stats.return_value = {}
    request = _Request(_Form([("model", "audio-alias")]))
    request.app = types.SimpleNamespace(state=state)

    with patch.object(
        request_module, "get_service_discovery", return_value=_discovery(ALIASES)
    ):
        resp = await request_module.proxy_multipart_request(
            b"raw-bytes", "audio-alias", "/v1/audio/translations", request
        )

    assert resp.status_code == 404
    assert b"No backend for model audio-alias" in resp.body


@pytest.mark.asyncio
async def test_proxy_multipart_canonical_model_reaches_backend():
    captured = {}

    class _FakeResp:
        status = 200
        headers = {"content-type": "application/json"}

        async def json(self):
            return {"ok": True}

        def close(self):
            pass

    async def _post(url, data=None, headers=None, timeout=None):
        captured.update(url=url, data=data)
        return _FakeResp()

    state = MagicMock()
    state.router = RoundRobinRouter()
    state.engine_stats_scraper.get_engine_stats.return_value = {}
    state.request_stats_monitor.get_request_stats.return_value = {}
    state.aiohttp_client_wrapper = lambda: types.SimpleNamespace(post=_post)
    request = _Request(_Form([("model", "openai/whisper-tiny")]))
    request.app = types.SimpleNamespace(state=state)

    with patch.object(
        request_module, "get_service_discovery", return_value=_discovery(ALIASES)
    ):
        resp = await request_module.proxy_multipart_request(
            b"raw-bytes", "openai/whisper-tiny", "/v1/audio/translations", request
        )

    assert resp.status_code == 200
    assert captured["url"] == "http://asr-engine/v1/audio/translations"
    assert captured["data"] == b"raw-bytes"
