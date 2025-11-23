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
from fastapi import APIRouter, BackgroundTasks, Request

from vllm_router.log import init_logger
from vllm_router.services.request_service.request import route_general_request

logger = init_logger(__name__)
anthropic_router = APIRouter()


@anthropic_router.post("/v1/messages")
async def route_anthropic_messages(request: Request, background_tasks: BackgroundTasks):
    """Route Anthropic-compatible messages requests to the backend."""
    return await route_general_request(request, "/v1/messages", background_tasks)
