import pytest
from opentelemetry.trace import SpanKind

import vllm_router.experimental.otel.tracing as tracing_module
from vllm_router.experimental.otel.tracing import (
    end_span,
    extract_context,
    initialize_tracing,
    inject_context,
    is_tracing_enabled,
    shutdown_tracing,
    start_span,
)


@pytest.fixture(autouse=True)
def reset_tracing_state():
    """Reset global tracing state before each test."""
    tracing_module._tracer = None
    tracing_module._provider = None
    tracing_module._tracing_enabled = False
    yield
    # Cleanup after test
    if tracing_module._tracing_enabled:
        shutdown_tracing()


class TestTracingIntegration:
    def test_full_request_flow(self):
        """Test a complete request tracing flow."""
        initialize_tracing(service_name="vllm-router", otlp_endpoint="localhost:4317")

        # Simulate incoming request with trace context
        incoming_headers = {
            "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
        }
        incoming_context = extract_context(incoming_headers)

        # Create parent span (router)
        parent_span, parent_context = start_span(
            name="router /v1/chat/completions",
            parent_context=incoming_context,
            kind=SpanKind.SERVER,
            attributes={
                "http.method": "POST",
                "vllm.model": "Qwen/Qwen2.5-7B-Instruct",
            },
        )

        # Create child span (backend request)
        child_span, child_context = start_span(
            name="backend_request",
            parent_context=parent_context,
            kind=SpanKind.CLIENT,
            attributes={
                "http.url": "http://backend:8000/v1/chat/completions",
            },
        )

        # Inject context into outgoing headers
        outgoing_headers = {}
        inject_context(outgoing_headers, child_context)

        assert "traceparent" in outgoing_headers

        # End spans in reverse order
        end_span(child_span, status_code=200)
        end_span(parent_span, status_code=200)

    def test_tracing_disabled_flow(self):
        """Test that operations handle disabled tracing gracefully."""
        assert is_tracing_enabled() is False

        # These should not raise even when tracing is disabled
        headers = {}
        inject_context(headers)
        end_span(None)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
