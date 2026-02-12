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

"""OpenTelemetry tracing utilities for vLLM Router.

This module provides distributed tracing support using OpenTelemetry.
It handles:
- Trace context extraction from incoming requests (W3C Trace Context)
- Span creation for router operations
- Trace context injection into outgoing requests to backends
"""

import logging
from typing import Any, Dict, Optional

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)

# Global state for tracing
_tracer: Optional[trace.Tracer] = None
_provider: Optional[TracerProvider] = None
_tracing_enabled: bool = False


def initialize_tracing(
    service_name: str = "vllm-router",
    otlp_endpoint: str = "localhost:4317",
    insecure: bool = True,
) -> None:
    """Initialize OpenTelemetry tracing with OTLP exporter.

    Args:
        service_name: The service name to use for traces.
        otlp_endpoint: The OTLP collector endpoint (e.g., "localhost:4317").
        insecure: Whether to use insecure connection (no TLS).
    """
    global _tracer, _provider, _tracing_enabled

    if _tracing_enabled:
        logger.warning("Tracing already initialized, skipping re-initialization")
        return

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": "1.0.0",
        }
    )
    exporter = OTLPSpanExporter(
        endpoint=otlp_endpoint,
        insecure=insecure,
    )
    _provider = TracerProvider(resource=resource)
    _provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(_provider)
    _tracer = trace.get_tracer("vllm-router")
    _tracing_enabled = True

    logger.info(
        f"OpenTelemetry tracing initialized: service={service_name}, "
        f"endpoint={otlp_endpoint}, insecure={insecure}"
    )


def shutdown_tracing() -> None:
    """Shutdown the tracer provider and flush pending spans."""
    global _provider, _tracing_enabled

    if _provider is not None:
        _provider.shutdown()
        logger.info("OpenTelemetry tracing shutdown complete")

    _tracing_enabled = False


def get_tracer() -> trace.Tracer:
    """Get the tracer instance.

    Returns:
        The tracer instance.

    Raises:
        RuntimeError: If tracing has not been initialized.
    """
    if _tracer is None:
        raise RuntimeError("Tracing not initialized. Call initialize_tracing() first.")
    return _tracer


def is_tracing_enabled() -> bool:
    """Check if tracing is enabled.

    Returns:
        True if tracing is initialized and enabled.
    """
    return _tracing_enabled


def extract_context(headers: Dict[str, Any]) -> Context:
    """Extract trace context from incoming request headers.

    This extracts W3C Trace Context (traceparent, tracestate) from headers.

    Args:
        headers: Dictionary of request headers.

    Returns:
        OpenTelemetry Context with extracted trace information.
    """
    return extract(carrier=headers)


def inject_context(
    headers: Dict[str, str], context: Optional[Context] = None
) -> Dict[str, str]:
    """Inject trace context into outgoing request headers.

    This injects W3C Trace Context (traceparent, tracestate) into headers.

    Args:
        headers: Dictionary of request headers to inject into.
        context: Optional context to inject. If None, uses current context.

    Returns:
        The headers dictionary with trace context added.
    """
    inject(carrier=headers, context=context)
    return headers


def start_span(
    name: str,
    parent_context: Optional[Context] = None,
    kind: trace.SpanKind = trace.SpanKind.SERVER,
    attributes: Optional[Dict[str, Any]] = None,
) -> tuple[trace.Span, Context]:
    """Start a new span and return both the span and its context.

    Args:
        name: Name of the span.
        parent_context: Parent context to create span under. If None, extracts from current context.
        kind: The span kind (SERVER, CLIENT, etc.).
        attributes: Optional dict of attributes to set on the span.

    Returns:
        Tuple of (span, span_context) where span_context can be used as parent for child spans.
    """
    tracer = get_tracer()
    span = tracer.start_span(name, context=parent_context, kind=kind)

    if attributes:
        for key, value in attributes.items():
            span.set_attribute(key, value)

    span_context = trace.set_span_in_context(span, parent_context)
    return span, span_context


def end_span(
    span: Optional[trace.Span],
    error: Optional[Exception] = None,
    status_code: Optional[int] = None,
) -> None:
    """End a span, optionally recording error information.

    Args:
        span: The span to end. If None, does nothing.
        error: Optional exception to record on the span.
        status_code: Optional HTTP status code to set on the span.
    """
    if span is None:
        return

    if status_code is not None:
        span.set_attribute("http.status_code", status_code)

    if error is not None:
        span.record_exception(error)
        span.set_status(trace.StatusCode.ERROR, str(error))

    span.end()
