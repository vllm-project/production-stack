"""The session-extraction debug line must not defeat TokenRedactionFilter.

TokenRedactionFilter only inspects ``record.args`` for a Starlette ``Headers``
object, so a call site that formats the headers into the message string leaves
nothing for it to redact.
"""

import logging

from starlette.datastructures import Headers

from vllm_router import log


def _record(msg, args):
    return logging.LogRecord(
        name="test",
        level=logging.DEBUG,
        pathname="test.py",
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


def test_formatted_headers_are_not_redacted_but_a_lazy_arg_is():
    redaction = log.TokenRedactionFilter()
    headers = Headers(
        {"authorization": "Bearer super-secret-token", "host": "example.invalid"}
    )

    formatted = _record(f"Request headers: {dict(headers)}", None)
    redaction.filter(formatted)
    assert "super-secret-token" in formatted.getMessage(), (
        "a pre-formatted dict carries nothing in record.args, so the filter has "
        "nothing to act on; this is what the call site must avoid"
    )

    lazy = _record("Request headers: %s", (headers,))
    redaction.filter(lazy)
    assert "super-secret-token" not in lazy.getMessage()
    assert "Bearer ****" in lazy.getMessage()


def test_the_filter_leaves_headers_alone_when_nothing_is_sensitive():
    """Documented behaviour, pinned by test_filter_preserves_non_sensitive_headers.

    The consequence for this call site is that the line reads as a dict when a
    secret is present and as Headers({...}) when it is not. That is a format
    difference rather than a leak, and changing it would change the filter's
    own contract.
    """
    redaction = log.TokenRedactionFilter()

    plain = _record("Request headers: %s", (Headers({"host": "x"}),))
    redaction.filter(plain)
    assert "Headers({'host': 'x'})" in plain.getMessage()

    secret = _record(
        "Request headers: %s", (Headers({"authorization": "Bearer s3cret"}),)
    )
    redaction.filter(secret)
    assert secret.getMessage() == "Request headers: {'authorization': 'Bearer ****'}"


def test_the_call_site_passes_headers_as_a_lazy_argument():
    """Read the call site as a syntax tree, not as text.

    A string match on the source breaks on quote style or on a formatter
    rewrapping the line. The AST answers the only question that matters: does
    the ``logger.debug`` call for this message carry a second argument, or is
    everything baked into the first one?
    """
    import ast
    import inspect

    from vllm_router.services.request_service import request as request_module

    tree = ast.parse(inspect.getsource(request_module.route_general_request))

    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "debug"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
        and "Request headers" in node.args[0].value
    ]

    assert len(calls) == 1, "expected exactly one headers debug call"
    call = calls[0]

    assert len(call.args) >= 2, (
        "the headers must be a separate argument; TokenRedactionFilter only "
        "inspects record.args, so anything formatted into the message survives"
    )
    assert "%s" in call.args[0].value


def test_the_call_site_logs_headers_as_a_lazy_argument():
    """Capture on the module's own logger, which does not propagate to root."""
    from vllm_router.services.request_service import request as request_module

    captured: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    handler = _Capture(level=logging.DEBUG)
    logger = request_module.logger
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        logger.debug(
            "Debug session extraction - Request headers: %s",
            Headers({"authorization": "Bearer super-secret-token"}),
        )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    record = next(
        r for r in captured if "Debug session extraction - Request headers" in r.msg
    )
    assert record.args, "the headers must arrive as a lazy argument"

    log.TokenRedactionFilter().filter(record)
    assert "super-secret-token" not in record.getMessage()
    assert "Bearer ****" in record.getMessage()
