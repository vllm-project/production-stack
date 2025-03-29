import logging
import sys
from logging import Logger


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


def init_logger(name: str, log_level=logging.DEBUG) -> Logger:
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

    return logger
