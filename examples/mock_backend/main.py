#!/usr/bin/env python3
"""
Mock vLLM backend used for local Swagger UI and routing smoke tests.

Features:
 - Implements /v1/chat/completions, /v1/completions, /v1/embeddings
 - Lightweight, deterministic style responses
 - Adjustable port via --port (default 8000)

This is NOT a production server; it's only for development / CI smoke tests.
"""

# Copyright 2024-2025 The vLLM Production Stack Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import argparse
import time
import uuid

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Mock vLLM Backend", version="1.0.0")


@app.post("/v1/chat/completions")
async def mock_chat_completions(
    request: Request,
):  # pragma: no cover - exercised in e2e
    body = await request.json()
    response = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:10]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "mock-model"),
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hello! This is a mock response from the Swagger UI integration test.",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
    }
    return JSONResponse(content=response)


@app.post("/v1/completions")
async def mock_completions(request: Request):  # pragma: no cover
    body = await request.json()
    response = {
        "id": f"cmpl-{uuid.uuid4().hex[:10]}",
        "object": "text_completion",
        "created": int(time.time()),
        "model": body.get("model", "mock-model"),
        "choices": [
            {
                "text": " This is a mock completion response.",
                "index": 0,
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 8, "total_tokens": 13},
    }
    return JSONResponse(content=response)


@app.post("/v1/embeddings")
async def mock_embeddings(request: Request):  # pragma: no cover
    body = await request.json()
    response = {
        "object": "list",
        "data": [
            {
                "object": "embedding",
                "embedding": [0.1, 0.2, 0.3, 0.4, 0.5] * 100,  # 500-dim
                "index": 0,
            }
        ],
        "model": body.get("model", "mock-embedding-model"),
        "usage": {"prompt_tokens": 8, "total_tokens": 8},
    }
    return JSONResponse(content=response)


@app.get("/health")
async def health():  # pragma: no cover
    return {"status": "healthy"}


def parse_args():  # pragma: no cover
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", type=str, default="0.0.0.0")
    return p.parse_args()


def main():  # pragma: no cover
    args = parse_args()
    print(f"🚀 Starting Mock vLLM Backend on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":  # pragma: no cover
    main()
