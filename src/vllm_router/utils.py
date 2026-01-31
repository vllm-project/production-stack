import abc
import enum
import io
import json
import re
import resource
import wave
from typing import Optional

import requests
from fastapi.requests import Request
from starlette.datastructures import MutableHeaders

from vllm_router.log import init_logger

logger = init_logger(__name__)

# prepare a WAV byte to prevent repeatedly generating it
# Generate a 0.1 second silent audio file
# This will be used for the /v1/audio/transcriptions endpoint
_SILENT_WAV_BYTES = None
with io.BytesIO() as wav_buffer:
    with wave.open(wav_buffer, "wb") as wf:
        wf.setnchannels(1)  # mono audio channel, standard configuration
        wf.setsampwidth(2)  # 16 bit audio, common bit depth for wav file
        wf.setframerate(16000)  # 16 kHz sample rate
        wf.writeframes(b"\x00\x00" * 1600)  # 0.1 second of silence

    # retrieves the generated wav bytes, return
    _SILENT_WAV_BYTES = wav_buffer.getvalue()
    logger.debug(
        "======A default silent WAV file has been stored in memory within py application process===="
    )


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
    chat = "chat"
    completion = "completion"
    embeddings = "embeddings"
    rerank = "rerank"
    score = "score"
    transcription = "transcription"
    vision = "vision"

    @staticmethod
    def get_url(model_type: str):
        match ModelType[model_type]:
            case ModelType.chat | ModelType.vision:
                return "/v1/chat/completions"
            case ModelType.completion:
                return "/v1/completions"
            case ModelType.embeddings:
                return "/v1/embeddings"
            case ModelType.rerank:
                return "/v1/rerank"
            case ModelType.score:
                return "/v1/score"
            case ModelType.transcription:
                return "/v1/audio/transcriptions"

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
                return {"encoding_format": "float", "text_1": "Test", "text_2": "Test2"}
            case ModelType.transcription:
                if _SILENT_WAV_BYTES is not None:
                    logger.debug("=====Silent WAV Bytes is being used=====")
                    return {
                        "file": ("empty.wav", _SILENT_WAV_BYTES, "audio/wav"),
                    }
            case ModelType.vision:
                return {
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "This is a test. Just reply with yes",
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": "data:image/jpeg;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAG0lEQVR4nGLinfJq851wJn69udZSvIAAAAD//yf3BLKCfW8HAAAAAElFTkSuQmCC"
                                    },
                                },
                            ],
                        }
                    ]
                }

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
    model_url = ModelType.get_url(model_type)

    try:
        if model_type == "transcription":
            # for transcription, the backend expects multipart/form-data with a file
            # we will use pre-generated silent wav bytes
            response = requests.post(
                f"{url}{model_url}",
                files=ModelType.get_test_payload(model_type),  # multipart/form-data
                data={"model": model},
                timeout=10,
            )
        else:
            # for other model types (chat, completion, etc.)
            response = requests.post(
                f"{url}{model_url}",
                headers={"Content-Type": "application/json"},
                json={"model": model} | ModelType.get_test_payload(model_type),
                timeout=10,
            )

        response.raise_for_status()

        if model_type == "transcription":
            return True
        else:
            response.json()  # verify it's valid json for other model types
            return True  # validation passed

    except requests.exceptions.RequestException as e:
        logger.debug(f"{model_type} Model {model} at {url} is not healthy: {e}")
        return False
