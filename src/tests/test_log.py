import json
import logging

import pytest
from starlette.datastructures import Headers, MutableHeaders

from vllm_router import log


class TestTokenRedactionFilter:
    """Test suite for TokenRedactionFilter."""

    @pytest.fixture
    def filter_instance(self):
        """Create a filter instance for testing."""
        return log.TokenRedactionFilter()

    @pytest.fixture
    def log_record(self):
        """Create a basic log record for testing."""
        return logging.LogRecord(
            name="test",
            level=logging.DEBUG,
            pathname="test.py",
            lineno=1,
            msg="Test message: %s",
            args=(),
            exc_info=None,
        )

    def test_redact_value_with_bearer_token_preserves_scheme(
        self, filter_instance: log.TokenRedactionFilter
    ):
        """Test that Bearer tokens are redacted while preserving the scheme."""
        result = filter_instance._redact_value("Bearer sk-1234567890")
        assert result == "Bearer ****"

    def test_redact_value_with_basic_token_preserves_scheme(
        self, filter_instance: log.TokenRedactionFilter
    ):
        """Test that Basic auth tokens are redacted while preserving the scheme."""
        result = filter_instance._redact_value("Basic dXNlcjpwYXNz")
        assert result == "Basic ****"

    def test_redact_value_with_token_scheme_preserves_scheme(
        self, filter_instance: log.TokenRedactionFilter
    ):
        """Test that Token scheme is preserved."""
        result = filter_instance._redact_value("Token abc123xyz")
        assert result == "Token ****"

    def test_redact_value_without_scheme_keeps_first_4_chars(
        self, filter_instance: log.TokenRedactionFilter
    ):
        """Test that tokens without schemes keep first 4 characters."""
        result = filter_instance._redact_value("sk-1234567890")
        assert result == "sk-1****"

    def test_redact_value_short_token_becomes_asterisks(
        self, filter_instance: log.TokenRedactionFilter
    ):
        """Test that short tokens (4 chars or less) are fully redacted."""
        result = filter_instance._redact_value("abc")
        assert result == "****"

    def test_filter_redacts_authorization_header(
        self, filter_instance: log.TokenRedactionFilter, log_record: logging.LogRecord
    ):
        """Test that authorization headers are redacted."""
        headers = Headers({"authorization": "Bearer secret-token-123", "user": "test"})
        log_record.args = (headers,)

        result = filter_instance.filter(log_record)

        assert result is True
        assert isinstance(log_record.args[0], dict)
        assert log_record.args[0]["authorization"] == "Bearer ****"
        assert log_record.args[0]["user"] == "test"

    def test_filter_redacts_api_key_header(
        self, filter_instance: log.TokenRedactionFilter, log_record: logging.LogRecord
    ):
        """Test that API key headers are redacted."""
        headers = Headers(
            {"x-api-key": "sk-1234567890", "content-type": "application/json"}
        )
        log_record.args = (headers,)

        result = filter_instance.filter(log_record)

        assert result is True
        assert log_record.args[0]["x-api-key"] == "sk-1****"
        assert log_record.args[0]["content-type"] == "application/json"

    def test_filter_redacts_cookie_header(
        self, filter_instance: log.TokenRedactionFilter, log_record: logging.LogRecord
    ):
        """Test that cookie headers are redacted."""
        headers = Headers({"cookie": "session=abc123def456", "host": "example.com"})
        log_record.args = (headers,)

        result = filter_instance.filter(log_record)

        assert result is True
        assert log_record.args[0]["cookie"] == "sess****"
        assert log_record.args[0]["host"] == "example.com"

    def test_filter_works_with_mutable_headers(
        self, filter_instance: log.TokenRedactionFilter, log_record: logging.LogRecord
    ):
        """Test that the filter works with MutableHeaders objects."""
        headers = MutableHeaders({"authorization": "Bearer token123"})
        log_record.args = (headers,)

        result = filter_instance.filter(log_record)

        assert result is True
        assert log_record.args[0]["authorization"] == "Bearer ****"

    def test_filter_preserves_non_sensitive_headers(
        self, filter_instance: log.TokenRedactionFilter, log_record: logging.LogRecord
    ):
        """Test that non-sensitive headers are not modified."""
        headers = Headers(
            {
                "content-type": "application/json",
                "user-agent": "test-client",
                "host": "example.com",
            }
        )
        log_record.args = (headers,)

        result = filter_instance.filter(log_record)

        assert result is True
        # When no sensitive headers are present, filter should not modify args
        assert isinstance(log_record.args[0], Headers)

    def test_filter_handles_multiple_sensitive_headers(
        self, filter_instance: log.TokenRedactionFilter, log_record: logging.LogRecord
    ):
        """Test that multiple sensitive headers are all redacted."""
        headers = Headers(
            {
                "Authorization": "Bearer token123",
                "x-api-key": "sk-abc123",
                "Cookie": "session=xyz789",
                "content-type": "application/json",
            }
        )
        log_record.args = (headers,)

        result = filter_instance.filter(log_record)

        assert result is True
        assert log_record.args[0]["authorization"] == "Bearer ****"
        assert log_record.args[0]["x-api-key"] == "sk-a****"
        assert log_record.args[0]["cookie"] == "sess****"
        assert log_record.args[0]["content-type"] == "application/json"

    def test_filter_returns_true_with_no_args(
        self, filter_instance: log.TokenRedactionFilter, log_record: logging.LogRecord
    ):
        """Test that the filter returns True when there are no args."""
        log_record.args = None

        result = filter_instance.filter(log_record)

        assert result is True

    def test_filter_returns_true_with_empty_args(
        self, filter_instance: log.TokenRedactionFilter, log_record: logging.LogRecord
    ):
        """Test that the filter returns True with empty args."""
        log_record.args = ()

        result = filter_instance.filter(log_record)

        assert result is True

    def test_filter_handles_non_headers_args(
        self, filter_instance: log.TokenRedactionFilter, log_record: logging.LogRecord
    ):
        """Test that the filter doesn't modify non-Headers arguments."""
        log_record.args = ("just a string", 123)

        result = filter_instance.filter(log_record)

        assert result is True
        assert log_record.args == ("just a string", 123)

    def test_filter_case_insensitive_header_matching(
        self, filter_instance: log.TokenRedactionFilter, log_record: logging.LogRecord
    ):
        """Test that header matching is case-insensitive."""
        headers = Headers(
            {
                "Authorization": "Bearer token123",
                "X-API-Key": "sk-abc123",
                "COOKIE": "session=xyz789",
            }
        )
        log_record.args = (headers,)

        result = filter_instance.filter(log_record)

        assert result is True
        assert log_record.args[0]["authorization"] == "Bearer ****"
        assert log_record.args[0]["x-api-key"] == "sk-a****"
        assert log_record.args[0]["cookie"] == "sess****"


class TestJsonFormatter:
    """Test suite for JsonFormatter and log format switching."""

    @pytest.fixture(autouse=True)
    def _cleanup_log_state(self):
        """Save and restore global log state to prevent test pollution."""
        orig_format = log._LOG_FORMAT
        orig_loggers = log._loggers.copy()
        yield
        log._LOG_FORMAT = orig_format
        log._loggers[:] = orig_loggers

    @pytest.fixture
    def log_record(self):
        """Create a basic log record for testing."""
        return logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Hello %s",
            args=("world",),
            exc_info=None,
        )

    @pytest.fixture
    def formatter(self):
        return log.JsonFormatter()

    def test_json_formatter_outputs_valid_json(self, formatter, log_record):
        """Test that JsonFormatter produces valid JSON with expected keys."""
        output = formatter.format(log_record)
        parsed = json.loads(output)
        for key in ("timestamp", "level", "logger", "message", "filename", "lineno"):
            assert key in parsed, f"Missing key: {key}"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.logger"
        assert parsed["message"] == "Hello world"
        assert parsed["filename"] == "test.py"
        assert parsed["lineno"] == 42

    def test_json_formatter_includes_exception(self, formatter):
        """Test that exception info is included when present."""
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="error occurred",
            args=(),
            exc_info=exc_info,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "exception" in parsed
        assert "ValueError: boom" in parsed["exception"]

    def test_json_formatter_excludes_exception_when_none(self, formatter, log_record):
        """Test that the exception key is absent for normal log records."""
        output = formatter.format(log_record)
        parsed = json.loads(output)
        assert "exception" not in parsed

    def test_set_log_format_switches_to_json(self):
        """Test that set_log_format('json') applies JsonFormatter to all handlers."""
        logger = log.init_logger("test.switch_json")
        log.set_log_format("json")
        for handler in logger.handlers:
            assert isinstance(handler.formatter, log.JsonFormatter)

    def test_set_log_format_switches_back_to_text(self):
        """Test that switching from json back to text restores CustomFormatter."""
        logger = log.init_logger("test.switch_text")
        log.set_log_format("json")
        log.set_log_format("text")
        for handler in logger.handlers:
            assert isinstance(handler.formatter, log.CustomFormatter)

    def test_init_logger_respects_json_format(self):
        """Test that init_logger uses JsonFormatter when _LOG_FORMAT is 'json'."""
        log._LOG_FORMAT = "json"
        logger = log.init_logger("test.init_json")
        for handler in logger.handlers:
            assert isinstance(handler.formatter, log.JsonFormatter)
