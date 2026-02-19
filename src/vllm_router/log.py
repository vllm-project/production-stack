import logging
import sys
from logging import Logger

from starlette.datastructures import Headers, MutableHeaders

_LOG_LEVEL = logging.INFO
_loggers: list[Logger] = []

_LEVEL_NAME_MAP = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
    "trace": logging.DEBUG,
}


def set_log_level(level_str: str) -> None:
    global _LOG_LEVEL
    _LOG_LEVEL = _LEVEL_NAME_MAP.get(level_str.lower(), logging.INFO)
    for logger in _loggers:
        logger.setLevel(_LOG_LEVEL)
        for handler in logger.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(
                handler, logging.FileHandler
            ):
                # Only lower the stdout handler level; keep the stderr
                # handler at WARNING so errors always surface.
                if handler.stream is sys.stdout:
                    handler.setLevel(_LOG_LEVEL)


def build_format(color):
    reset = "\x1b[0m"
    underline = "\x1b[3m"
    return f"{color}[%(asctime)s] %(levelname)s:{reset} %(message)s {underline}(%(filename)s:%(lineno)d:%(name)s){reset}"


class CustomFormatter(logging.Formatter):
    grey = "\x1b[1m"
    green = "\x1b[32;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"

    FORMATS = {
        logging.DEBUG: build_format(grey),
        logging.INFO: build_format(green),
        logging.WARNING: build_format(yellow),
        logging.ERROR: build_format(red),
        logging.CRITICAL: build_format(bold_red),
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


class MaxLevelFilter(logging.Filter):
    def __init__(self, max_level: int):
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.max_level


# Sensitive headers that commonly contain authentication tokens
_SENSITIVE_HEADERS = {
    "authorization",
    "x-api-key",
    "api-key",
    "x-auth-token",
    "auth-token",
    "x-access-token",
    "access-token",
    "cookie",
    "set-cookie",
}

# Common authentication schemes to preserve when redacting
_AUTH_SCHEMES = {
    "bearer",
    "basic",
    "token",
    "digest",
    "oauth",
    "apikey",
}


class TokenRedactionFilter(logging.Filter):
    """Logger filter that redacts sensitive tokens from Starlette Headers objects."""

    def _redact_value(self, value: str) -> str:
        """
        Redact a sensitive value, preserving auth scheme prefixes if present.

        Examples:
            "Bearer sk-1234567890" -> "Bearer ****"
            "Basic dXNlcjpwYXNz" -> "Basic ****"
            "sk-1234567890" -> "sk-1****"
        """
        value_str = str(value)

        # Check if value starts with a known auth scheme
        if " " in value_str:
            parts = value_str.split(" ", 1)
            if len(parts) == 2 and parts[0].lower() in _AUTH_SCHEMES:
                return f"{parts[0]} ****"

        # Default redaction: keep first 4 characters
        if len(value_str) > 4:
            return value_str[:4] + "****"
        return "****"

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Redact sensitive header values in log messages.

        This filter specifically checks for Starlette Headers objects and redacts
        their sensitive values before the message is emitted.
        """
        # Check if there are args that might contain headers
        if hasattr(record, "args") and record.args:
            # Convert args to list for modification
            args_list = (
                list(record.args) if isinstance(record.args, tuple) else [record.args]
            )
            modified = False

            for i, arg in enumerate(args_list):
                # Check if arg is a Starlette Headers object
                if isinstance(arg, (Headers, MutableHeaders)):
                    arg_was_modified = False
                    redacted_dict = {}
                    for key, value in arg.items():
                        if isinstance(key, str) and key.lower() in _SENSITIVE_HEADERS:
                            # Redact the value
                            redacted_dict[key] = self._redact_value(value)
                            arg_was_modified = True
                        else:
                            redacted_dict[key] = value
                    if arg_was_modified:
                        args_list[i] = redacted_dict
                        modified = True

            if modified:
                record.args = (
                    tuple(args_list) if isinstance(record.args, tuple) else args_list[0]
                )

        return True


def init_logger(name: str, log_level=None) -> Logger:
    if log_level is None:
        log_level = _LOG_LEVEL

    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    stdout_stream = logging.StreamHandler(sys.stdout)
    stdout_stream.setLevel(log_level)
    stdout_stream.setFormatter(CustomFormatter())
    stdout_stream.addFilter(MaxLevelFilter(logging.INFO))
    stdout_stream.addFilter(TokenRedactionFilter())
    logger.addHandler(stdout_stream)

    error_stream = logging.StreamHandler()
    error_stream.setLevel(logging.WARNING)
    error_stream.setFormatter(CustomFormatter())
    logger.addHandler(error_stream)
    logger.propagate = False

    _loggers.append(logger)
    return logger
