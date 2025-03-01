import abc
import re
import resource

from vllm_router.log import init_logger

logger = init_logger(__name__)


class SingletonMeta(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        """
        Note: if the class is called with _create=False, it will return None
        if the instance does not exist.
        """
        if cls not in cls._instances:
            if kwargs.get("_create") is False:
                return None
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]


class SingletonABCMeta(abc.ABCMeta):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        """
        Note: if the class is called with _create=False, it will return None
        if the instance does not exist.
        """
        if cls not in cls._instances:
            if kwargs.get("create") is False:
                return None
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]


def validate_url(url: str) -> bool:
    """
    Validates the format of the given URL.

    Args:
        url (str): The URL to validate.

    Returns:
        bool: True if the URL is valid, False otherwise.
    """
    regex = re.compile(
        r"^(http|https)://"  # Protocol
        r"(([a-zA-Z0-9_-]+\.)+[a-zA-Z]{2,}|"  # Domain name
        r"localhost|"  # Or localhost
        r"\d{1,3}(\.\d{1,3}){3})"  # Or IPv4 address
        r"(:\d+)?"  # Optional port
        r"(/.*)?$"  # Optional path
    )
    return bool(regex.match(url))


# Adapted from: https://github.com/sgl-project/sglang/blob/v0.4.1/python/sglang/srt/utils.py#L630 # noqa: E501
def set_ulimit(target_soft_limit=65535):
    resource_type = resource.RLIMIT_NOFILE
    current_soft, current_hard = resource.getrlimit(resource_type)

    if current_soft < target_soft_limit:
        try:
            resource.setrlimit(resource_type, (target_soft_limit, current_hard))
        except ValueError as e:
            logger.warning(
                "Found ulimit of %s and failed to automatically increase"
                "with error %s. This can cause fd limit errors like"
                "`OSError: [Errno 24] Too many open files`. Consider "
                "increasing with ulimit -n",
                current_soft,
                e,
            )


def parse_static_urls(static_backends: str):
    urls = static_backends.split(",")
    backend_urls = []
    for url in urls:
        if validate_url(url):
            backend_urls.append(url)
        else:
            logger.warning(f"Skipping invalid URL: {url}")
    return backend_urls


def parse_static_model_names(static_models: str):
    models = static_models.split(",")
    return models
