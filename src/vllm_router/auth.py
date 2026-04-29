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
import os
from typing import FrozenSet

from fastapi import HTTPException, Request

from vllm_router.log import init_logger

logger = init_logger(__name__)


def _parse_api_keys(raw: str) -> FrozenSet[str]:
    """
    Parse a comma-separated API key string into a frozenset of non-empty keys.

    Leading/trailing whitespace around each key is stripped so that
    ``"key1, key2 , key3"`` is treated identically to ``"key1,key2,key3"``.
    """
    return frozenset(k.strip() for k in raw.split(",") if k.strip())


def get_allowed_api_keys() -> FrozenSet[str]:
    """
    Return the set of valid API keys sourced from the ``VLLM_API_KEY``
    environment variable.  Returns an empty frozenset when the variable is
    unset or empty, which disables authentication entirely.
    """
    raw = os.getenv("VLLM_API_KEY", "")
    return _parse_api_keys(raw)


async def verify_api_key(request: Request) -> None:
    """
    FastAPI dependency that enforces Bearer-token authentication.

    When ``VLLM_API_KEY`` is set the incoming ``Authorization`` header must
    carry one of the configured keys.  Requests without a valid token receive
    a 401 response.  When ``VLLM_API_KEY`` is not configured this dependency
    is a no-op and all requests are allowed through.
    """
    allowed_keys = get_allowed_api_keys()
    if not allowed_keys:
        return

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or malformed Authorization header. Expected: Bearer <token>",
        )

    token = auth_header[len("Bearer ") :].strip()
    if token not in allowed_keys:
        raise HTTPException(status_code=401, detail="Invalid API key")
