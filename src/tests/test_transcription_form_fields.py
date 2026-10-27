"""The transcription route forwards every form field the client sent, not just
the ones it normalizes, as /v1/audio/translations already does."""

import io
from unittest.mock import AsyncMock, patch

import pytest
from starlette.datastructures import FormData, Headers, UploadFile

from vllm_router.services.request_service import request as request_module


class _Request:
    def __init__(self, form):
        self._form = form
        self.headers = Headers({})

    async def form(self):
        return self._form


@pytest.mark.asyncio
async def test_transcription_forwards_extra_form_fields():
    audio = UploadFile(
        io.BytesIO(b"RIFF"),
        filename="a.wav",
        headers=Headers({"content-type": "audio/wav"}),
    )
    form = FormData(
        [
            ("file", audio),
            ("model", "whisper"),
            ("seed", "7"),
            ("top_p", "0.9"),
            ("timestamp_granularities[]", "word"),
            ("timestamp_granularities[]", "segment"),
        ]
    )
    proxy = AsyncMock(return_value="ok")
    with patch.object(request_module, "proxy_multipart_request", proxy):
        await request_module.route_general_transcriptions(
            _Request(form), "/v1/audio/transcriptions", None
        )

    sent = proxy.await_args.args[0]
    fields = [(opts["name"], value) for opts, _, value in sent._fields]
    assert ("seed", "7") in fields
    assert ("top_p", "0.9") in fields
    assert ("timestamp_granularities[]", "word") in fields
    assert ("timestamp_granularities[]", "segment") in fields
    assert [name for name, _ in fields].count("model") == 1
