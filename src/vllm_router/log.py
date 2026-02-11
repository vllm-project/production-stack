import logging
import sys
from logging import Logger

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


def init_logger(name: str, log_level=None) -> Logger:
    if log_level is None:
        log_level = _LOG_LEVEL

    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    stdout_stream = logging.StreamHandler(sys.stdout)
    stdout_stream.setLevel(log_level)
    stdout_stream.setFormatter(CustomFormatter())
    stdout_stream.addFilter(MaxLevelFilter(logging.INFO))
    logger.addHandler(stdout_stream)

    error_stream = logging.StreamHandler()
    error_stream.setLevel(logging.WARNING)
    error_stream.setFormatter(CustomFormatter())
    logger.addHandler(error_stream)
    logger.propagate = False

    _loggers.append(logger)
    return logger
