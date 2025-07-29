import abc
import enum
import json
import re
import resource
from typing import Optional

import requests
from fastapi.requests import Request
from starlette.datastructures import MutableHeaders

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


class ModelType(enum.Enum):
    chat = "/v1/chat/completions"
    completion = "/v1/completions"
    embeddings = "/v1/embeddings"
    rerank = "/v1/rerank"
    score = "/v1/score"

    @staticmethod
    def get_test_payload(model_type: str):
        match ModelType[model_type]:
            case ModelType.chat:
                return {
                    "messages": [
                        {
                            "role": "user",
                            "content": "Hello",
                        }
                    ],
                    "temperature": 0.0,
                    "max_tokens": 3,
                }
            case ModelType.completion:
                return {"prompt": "Hello", "max_tokens": 3}
            case ModelType.embeddings:
                return {"input": "Hello"}
            case ModelType.rerank:
                return {"query": "Hello", "documents": ["Test"]}
            case ModelType.score:
                return {"encoding_format": "float", "text_1": "Test", "test_2": "Test2"}

    @staticmethod
    def get_all_fields():
        return [model_type.name for model_type in ModelType]


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


def parse_comma_separated_args(comma_separated_string: Optional[str]):
    if comma_separated_string is None:
        return None
    return comma_separated_string.split(",")


def parse_static_aliases(static_aliases: str):
    aliases = {}
    for alias_and_model in static_aliases.split(","):
        alias, model = alias_and_model.split(":")
        aliases[alias] = model
    logger.info(f"Loaded aliases {aliases}")
    return aliases


def replace_model_in_request_body(request_json: dict, model: str):
    request_json["model"] = model
    request_body = json.dumps(request_json)
    return request_body


def update_content_length(request: Request, request_body: str):
    headers = MutableHeaders(request.headers)
    headers["Content-Length"] = str(len(request_body))
    request._headers = headers


def is_model_healthy(url: str, model: str, model_type: str) -> bool:
    model_details = ModelType[model_type]
    try:
        response = requests.post(
            f"{url}{model_details.value}",
            headers={"Content-Type": "application/json"},
            json={"model": model} | model_details.get_test_payload(model_type),
            timeout=30,
        )
    except Exception as e:
        logger.error(e)
        return False
    return response.status_code == 200
