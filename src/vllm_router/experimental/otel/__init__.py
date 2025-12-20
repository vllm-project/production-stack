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

"""OpenTelemetry tracing module for vLLM Router."""

from vllm_router.experimental.otel.tracing import (
    end_span,
    extract_context,
    get_tracer,
    initialize_tracing,
    inject_context,
    is_tracing_enabled,
    shutdown_tracing,
    start_span,
)

__all__ = [
    "initialize_tracing",
    "shutdown_tracing",
    "get_tracer",
    "is_tracing_enabled",
    "extract_context",
    "inject_context",
    "start_span",
    "end_span",
]
