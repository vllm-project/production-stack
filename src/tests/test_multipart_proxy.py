import asyncio
from contextlib import AsyncExitStack, asynccontextmanager

import httpx
import pytest
import starlette.formparsers
from aiohttp import web
from aiohttp.test_utils import TestServer
from fastapi import FastAPI
from starlette.datastructures import UploadFile

import vllm_router.service_discovery as service_discovery_module
from vllm_router.aiohttp_client import AiohttpClientWrapper
from vllm_router.routers.main_router import main_router
from vllm_router.routers.routing_logic import (
    RoutingLogic,
    cleanup_routing_logic,
    initialize_routing_logic,
)
from vllm_router.service_discovery import (
    ServiceDiscoveryType,
    initialize_service_discovery,
)
from vllm_router.stats.engine_stats import (
    EngineStatsScraper,
    initialize_engine_stats_scraper,
)
from vllm_router.stats.request_stats import (
    RequestStatsMonitor,
)
from vllm_router.stats.request_stats import SingletonMeta as RequestStatsSingletonMeta
from vllm_router.stats.request_stats import (
    initialize_request_stats_monitor,
)
from vllm_router.utils import SingletonMeta

AUDIO_MODEL = "openai/whisper-tiny"
IMAGE_MODEL = "image-edit-model"


@pytest.fixture
def multipart_upload_files(monkeypatch):
    # Keep handles observable after the request instead of relying on GC.
    files = []
    spooled_temporary_file = starlette.formparsers.SpooledTemporaryFile

    def record_file(*args, **kwargs):
        file = spooled_temporary_file(*args, **kwargs)
        files.append(file)
        return file

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", record_file)
    # Exercise real disk-backed uploads without sending large request bodies.
    monkeypatch.setattr(starlette.formparsers.MultiPartParser, "spool_max_size", 1)
    try:
        yield files
    finally:
        for file in files:
            file.close()


@asynccontextmanager
async def multipart_backend(endpoint, handler):
    app = web.Application()
    app.router.add_post(endpoint, handler)

    async def metrics(_):
        return web.Response(text="")

    app.router.add_get("/metrics", metrics)

    async with TestServer(app) as server:
        yield str(server.make_url("/")).rstrip("/")


@asynccontextmanager
async def router_client(backend_url, model=AUDIO_MODEL, aliases=None):
    app = FastAPI()
    app.include_router(main_router)

    async with AsyncExitStack() as stack:
        service_discovery = initialize_service_discovery(
            ServiceDiscoveryType.STATIC,
            app=app,
            urls=[backend_url],
            models=[model],
            aliases=aliases,
        )
        stack.callback(
            setattr, service_discovery_module, "_global_service_discovery", None
        )
        stack.callback(service_discovery.close)

        engine_stats = initialize_engine_stats_scraper(1)
        stack.callback(SingletonMeta._instances.pop, EngineStatsScraper, None)
        stack.push_async_callback(asyncio.to_thread, engine_stats.close)

        request_stats = initialize_request_stats_monitor(10)
        stack.callback(
            RequestStatsSingletonMeta._instances.pop, RequestStatsMonitor, None
        )

        router = initialize_routing_logic(
            RoutingLogic.ROUND_ROBIN,
            max_instance_failover_reroute_attempts=0,
        )
        stack.callback(cleanup_routing_logic)

        aiohttp_client = AiohttpClientWrapper()
        aiohttp_client.start()
        stack.push_async_callback(aiohttp_client.stop)

        app.state.engine_stats_scraper = engine_stats
        app.state.request_stats_monitor = request_stats
        app.state.router = router
        app.state.aiohttp_client_wrapper = aiohttp_client
        app.state.otel_enabled = False

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://router"
        ) as client:
            yield client


@pytest.mark.asyncio
async def test_audio_translation_accepts_standard_multipart_request():
    received = {}

    async def translate(request):
        form = await request.post()
        upload = form["file"]
        received.update(
            model=form["model"],
            filename=upload.filename,
            content_type=upload.content_type,
            content=upload.file.read(),
        )
        return web.json_response({"text": "translated"})

    async with multipart_backend("/v1/audio/translations", translate) as backend_url:
        async with router_client(backend_url) as client:
            response = await client.post(
                "/v1/audio/translations",
                data={"model": AUDIO_MODEL},
                files={"file": ("speech.wav", b"fake-audio", "audio/wav")},
            )

    assert response.status_code == 200
    assert response.json() == {"text": "translated"}
    assert received == {
        "model": AUDIO_MODEL,
        "filename": "speech.wav",
        "content_type": "audio/wav",
        "content": b"fake-audio",
    }


@pytest.mark.asyncio
async def test_audio_translation_preserves_plain_text_response():
    received = {}

    async def translate(request):
        form = await request.post()
        received["response_format"] = form["response_format"]
        return web.Response(text="translated text", content_type="text/plain")

    async with multipart_backend("/v1/audio/translations", translate) as backend_url:
        async with router_client(backend_url) as client:
            response = await client.post(
                "/v1/audio/translations",
                data={"model": AUDIO_MODEL, "response_format": "text"},
                files={"file": ("speech.wav", b"fake-audio", "audio/wav")},
            )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "translated text"
    assert received == {"response_format": "text"}


@pytest.mark.asyncio
async def test_audio_transcription_preserves_plain_text_response():
    received = {}

    async def transcribe(request):
        form = await request.post()
        upload = form["file"]
        received.update(
            model=form["model"],
            response_format=form["response_format"],
            # absent by default so the backend auto-detects; None documents that
            language=form.get("language"),
            filename=upload.filename,
            content_type=upload.content_type,
            content=upload.file.read(),
        )
        return web.Response(text="transcribed text", content_type="text/plain")

    async with multipart_backend("/v1/audio/transcriptions", transcribe) as backend_url:
        async with router_client(backend_url) as client:
            response = await client.post(
                "/v1/audio/transcriptions",
                data={"model": AUDIO_MODEL, "response_format": "text"},
                files={"file": ("speech.wav", b"fake-audio", "audio/wav")},
            )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "transcribed text"
    assert received == {
        "model": AUDIO_MODEL,
        "response_format": "text",
        "language": None,
        "filename": "speech.wav",
        "content_type": "audio/wav",
        "content": b"fake-audio",
    }


@pytest.mark.asyncio
async def test_image_edit_accepts_standard_multipart_request():
    received = {}

    async def edit_image(request):
        form = await request.post()
        upload = form["image"]
        received.update(
            model=form["model"],
            prompt=form["prompt"],
            filename=upload.filename,
            content_type=upload.content_type,
            content=upload.file.read(),
        )
        return web.json_response({"data": [{"url": "https://example.test/edit.png"}]})

    async with multipart_backend("/v1/images/edits", edit_image) as backend_url:
        async with router_client(backend_url, model=IMAGE_MODEL) as client:
            response = await client.post(
                "/v1/images/edits",
                data={"model": IMAGE_MODEL, "prompt": "add a hat"},
                files={"image": ("input.png", b"fake-image", "image/png")},
            )

    assert response.status_code == 200
    assert response.json() == {"data": [{"url": "https://example.test/edit.png"}]}
    assert received == {
        "model": IMAGE_MODEL,
        "prompt": "add a hat",
        "filename": "input.png",
        "content_type": "image/png",
        "content": b"fake-image",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("use_alias", [False, True])
@pytest.mark.parametrize(
    "endpoint,model,upload_key,stream,filename",
    [
        ("/v1/audio/transcriptions", AUDIO_MODEL, "file", False, "input.bin"),
        ("/v1/audio/transcriptions", AUDIO_MODEL, "file", True, "input.bin"),
        ("/v1/audio/translations", AUDIO_MODEL, "file", False, "input.bin"),
        ("/v1/audio/translations", AUDIO_MODEL, "file", False, "speech sample.wav"),
        ("/v1/audio/translations", AUDIO_MODEL, "file", False, "语音.wav"),
        ("/v1/images/edits", IMAGE_MODEL, "image", False, "input.bin"),
        ("/v1/images/edits", IMAGE_MODEL, "image", False, "input image.png"),
        ("/v1/images/edits", IMAGE_MODEL, "image", False, "图像.png"),
    ],
)
async def test_multipart_model_aliases(
    endpoint, model, upload_key, stream, filename, use_alias
):
    received = {}
    alias = "model-alias"
    content = b"\x00\xffmodel-alias\x80"

    async def capture(request):
        form = await request.post()
        upload = form[upload_key]
        received.update(
            model=form["model"],
            prompt=form["prompt"],
            filename=upload.filename,
            content_type=upload.content_type,
            content=upload.file.read(),
            stream=form.get("stream"),
        )
        if stream:
            return web.Response(
                text='data: {"text": "transcribed"}\n\n',
                content_type="text/event-stream",
            )
        return web.json_response({"text": "processed"})

    async with multipart_backend(endpoint, capture) as backend_url:
        async with router_client(
            backend_url, model=model, aliases={alias: model}
        ) as client:
            data = {"model": alias if use_alias else model, "prompt": alias}
            if stream:
                data["stream"] = "true"
            response = await client.post(
                endpoint,
                data=data,
                files={upload_key: (filename, content, "application/octet-stream")},
            )

    assert response.status_code == 200
    if stream:
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.text == 'data: {"text": "transcribed"}\n\n'
    else:
        assert response.json() == {"text": "processed"}
    assert received == {
        "model": model,
        "prompt": alias,
        "filename": filename,
        "content_type": "application/octet-stream",
        "content": content,
        "stream": "true" if stream else None,
    }


@pytest.mark.asyncio
async def test_image_edit_alias_preserves_repeated_fields_and_uploads():
    received = {}

    async def capture(request):
        form = await request.post()
        received["model"] = form["model"]
        received["images"] = [
            (upload.filename, upload.content_type, upload.file.read())
            for upload in form.getall("image")
        ]
        received["extra"] = form.getall("extra")
        return web.json_response({"data": []})

    async with multipart_backend("/v1/images/edits", capture) as backend_url:
        async with router_client(
            backend_url, model=IMAGE_MODEL, aliases={"image-alias": IMAGE_MODEL}
        ) as client:
            response = await client.post(
                "/v1/images/edits",
                data={"model": "image-alias", "extra": ["first", "second"]},
                files=[
                    ("image", ("first.png", b"first-image", "image/png")),
                    ("image", ("second.png", b"second-image", "image/png")),
                ],
            )

    assert response.status_code == 200
    assert received == {
        "model": IMAGE_MODEL,
        "images": [
            ("first.png", "image/png", b"first-image"),
            ("second.png", "image/png", b"second-image"),
        ],
        "extra": ["first", "second"],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint,model,upload_key",
    [
        ("/v1/audio/translations", AUDIO_MODEL, "file"),
        ("/v1/images/edits", IMAGE_MODEL, "image"),
    ],
)
@pytest.mark.parametrize(
    "requested_model,expected_status",
    [("canonical", 200), ("alias", 200), (None, 400), ("unknown", 404)],
)
async def test_multipart_request_closes_uploads(
    endpoint,
    model,
    upload_key,
    requested_model,
    expected_status,
    multipart_upload_files,
):
    async def capture(request):
        form = await request.post()
        assert form["model"] == model
        assert len(form.getall(upload_key)) == 2
        return web.json_response({"text": "processed"})

    async with multipart_backend(endpoint, capture) as backend_url:
        async with router_client(
            backend_url, model=model, aliases={"model-alias": model}
        ) as client:
            models = {"canonical": model, "alias": "model-alias", "unknown": "unknown"}
            data = {"model": models[requested_model]} if requested_model else {}
            response = await client.post(
                endpoint,
                data=data,
                files=[
                    (upload_key, ("first.bin", b"first-upload")),
                    (upload_key, ("second.bin", b"second-upload")),
                ],
            )

    assert response.status_code == expected_status
    assert len(multipart_upload_files) == 2
    assert all(file._rolled for file in multipart_upload_files)
    assert all(file.closed for file in multipart_upload_files)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint,model,upload_key",
    [
        ("/v1/audio/translations", AUDIO_MODEL, "file"),
        ("/v1/images/edits", IMAGE_MODEL, "image"),
    ],
)
async def test_multipart_request_closes_uploads_when_read_fails(
    endpoint, model, upload_key, multipart_upload_files, monkeypatch
):
    async def fail_read(self, size=-1):
        raise OSError("upload read failed")

    monkeypatch.setattr(UploadFile, "read", fail_read)

    async def unexpected_request(request):
        pytest.fail("An upload read failure must not reach the backend")

    async with multipart_backend(endpoint, unexpected_request) as backend_url:
        async with router_client(
            backend_url, model=model, aliases={"model-alias": model}
        ) as client:
            with pytest.raises(OSError, match="upload read failed"):
                await client.post(
                    endpoint,
                    data={"model": "model-alias"},
                    files=[
                        (upload_key, ("first.bin", b"first-upload")),
                        (upload_key, ("second.bin", b"second-upload")),
                    ],
                )

    assert len(multipart_upload_files) == 2
    assert all(file._rolled for file in multipart_upload_files)
    assert all(file.closed for file in multipart_upload_files)
