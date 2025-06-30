import json
from unittest.mock import MagicMock

import pytest
from starlette.datastructures import MutableHeaders

from vllm_router import utils


@pytest.mark.parametrize(
    "aliases,expected_result",
    (
        ("gpt-4:mistral-nemo-instruct-2407", {"gpt-4": "mistral-nemo-instruct-2407"}),
        (
            "gpt-4:mistral-nemo-instruct-2407,gpt-3.5:mistral-nemo-instruct-2407",
            {
                "gpt-4": "mistral-nemo-instruct-2407",
                "gpt-3.5": "mistral-nemo-instruct-2407",
            },
        ),
        (
            "gpt-4:deepseek-r1-distill-qwen-7b,mistral-7b-instruct:mistral-nemo-instruct-2407",
            {
                "gpt-4": "deepseek-r1-distill-qwen-7b",
                "mistral-7b-instruct": "mistral-nemo-instruct-2407",
            },
        ),
    ),
)
def test_parse_static_aliases_when_aliases_as_string_supplied_returns_dict(
    aliases: str, expected_result: dict
) -> None:
    assert utils.parse_static_aliases(aliases) == expected_result


def test_replace_model_in_request_body_replaces_model() -> None:
    model = "mistral-nemo-instruct-2407"
    result = json.loads(
        utils.replace_model_in_request_body(
            {
                "model": "gpt-4",
                "prompt": "Hello",
                "max_tokens": 10,
                "temperature": 0.7,
            },
            model,
        )
    )
    assert result["model"] == model


def test_update_content_length_modifies_content_length_header() -> None:
    request_mock = MagicMock(
        headers={"Content-Length": "100", "Content-Type": "application/json"}
    )
    request_body = json.dumps({"request_body": 1})
    utils.update_content_length(request_mock, request_body)
    assert request_mock._headers == MutableHeaders(
        {
            "Content-Length": str(len(request_body)),
            "Content-Type": "application/json",
        }
    )
