"""Exercise the router's multipart aliases against backend form parsers."""

import aiohttp
import httpx
import pytest
import pytest_asyncio
from aiohttp import web
from fastapi import FastAPI, Request

from .test_multipart_proxy import multipart_backend, router_client

pytestmark = pytest.mark.asyncio(loop_scope="module")
MODEL = "canonical-model"
ALIAS = "client-alias"
TRANSCRIBE = "/v1/audio/transcriptions"
TRANSLATE = "/v1/audio/translations"
EDIT = "/v1/images/edits"
PROMPT = 'héllo "x"\n中文'
CONTENT = b"\x00\xffupload"
MULTIPART = "multipart/form-data"


def describe_parts(items):
    parts = []
    for name, value in items:
        if not isinstance(value, str):
            value = [value.filename, value.content_type, value.file.read().hex()]
        parts.append([name, value])
    return parts


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def client():
    async def receive(request):
        if request.content_type != MULTIPART:
            raise web.HTTPUnsupportedMediaType()
        if request.headers.get("Accept") == MULTIPART:
            return web.Response(
                body=await request.read(),
                headers={"Content-Type": request.headers["Content-Type"]},
            )
        parts = describe_parts((await request.post()).items())
        return web.json_response(parts, headers={"X-Backend-Path": request.path})

    async with (
        multipart_backend("/{path:.*}", receive) as url,
        router_client(url, MODEL, aliases={ALIAS: MODEL, "": MODEL}) as client,
    ):
        yield client


@pytest.mark.parametrize(
    "path, alias, field, filename, media_type",
    [
        (TRANSCRIBE, ALIAS, "file", "speech.wav", "audio/wav"),
        (TRANSLATE, ALIAS, "file", "my file é.wav", "audio/wav"),
        (EDIT, "", "image", "中文.png", "image/png"),
    ],
)
async def test_alias_reaches_canonical_backend(
    client, path, alias, field, filename, media_type
):
    response = await client.post(
        path,
        data={"model": alias, "prompt": PROMPT},
        files={field: (filename, CONTENT, media_type)},
    )
    assert response.status_code == 200
    assert response.headers["X-Backend-Path"] == path
    parts = dict(response.json())
    assert parts["model"] == MODEL
    assert parts["prompt"] == PROMPT
    assert parts[field] == [filename, media_type, CONTENT.hex()]


@pytest.mark.parametrize("path", [TRANSLATE, EDIT])
async def test_canonical_body_and_boundary_are_unchanged(client, path):
    request = client.build_request(
        "POST",
        path,
        data={"model": MODEL},
        files={"file": ("my file é.wav", CONTENT)},
        headers={"Accept": MULTIPART},
    )
    body = await request.aread()
    response = await client.send(request)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == request.headers["Content-Type"]
    assert response.content == body


async def test_mixed_models_are_normalized(client):
    response = await client.post(
        EDIT, files=[("model", (None, ALIAS)), ("model", (None, MODEL))]
    )
    assert response.status_code == 200
    assert response.json() == [["model", MODEL], ["model", MODEL]]


async def parse_at_fastapi(forwarded):
    app = FastAPI()

    @app.post("/")
    async def receive(request: Request):
        async with request.form() as form:
            return describe_parts(form.multi_items())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as backend:
        return await backend.post(
            "http://backend/",
            content=forwarded.content,
            headers={"Content-Type": forwarded.headers["Content-Type"]},
        )


@pytest.mark.parametrize("backend", ["aiohttp", "fastapi"])
async def test_field_names_and_filenames_round_trip(client, backend):
    names = [
        "my file é.wav",
        "中文",
        r'say "hi"\take.wav',
        "semi;colon",
        "clip; filename*=UTF-8''other.wav",
    ]
    # HTTPX encodes literal double quotes as %22. Send MIME quoted-pairs on the wire.
    form = aiohttp.FormData(quote_fields=False)
    form.add_field("model", ALIAS)
    form.add_field("prompt", PROMPT)
    for name in names:
        form.add_field(name, CONTENT, filename=name, content_type="audio/wav")
    payload = form()
    headers = dict(payload.headers)
    if backend == "fastapi":
        headers["Accept"] = MULTIPART
    response = await client.post(
        TRANSLATE, content=await payload.as_bytes(), headers=headers
    )
    assert response.status_code == 200
    if backend == "fastapi":
        response = await parse_at_fastapi(response)
        assert response.status_code == 200
    assert response.json() == [
        ["model", MODEL],
        ["prompt", PROMPT],
        *[[name, [name, "audio/wav", CONTENT.hex()]] for name in names],
    ]


@pytest.mark.parametrize(
    "path,model,status",
    [(EDIT, "unknown", 404), (EDIT, None, 400), (TRANSCRIBE, None, 400)],
)
async def test_model_errors(client, path, model, status):
    data = {"model": model} if model else {}
    response = await client.post(path, data=data, files={"file": ("f.wav", CONTENT)})
    assert response.status_code == status
    assert response.json()["error"] == (
        f"No backend for model {model}"
        if model
        else "Invalid request: missing 'model' in form data."
    )


@pytest.mark.parametrize(
    "field,filename,control", [("f@le", "a.wav", b"\r"), ("file", "a@wav", b"\n")]
)
async def test_invalid_part_headers_return_400(client, field, filename, control):
    files = {field: (filename, CONTENT)}
    request = client.build_request(
        "POST", TRANSLATE, data={"model": ALIAS}, files=files
    )
    body = (await request.aread()).replace(b"@", control)
    response = await client.post(TRANSLATE, content=body, headers=request.headers)
    assert response.status_code == 400
