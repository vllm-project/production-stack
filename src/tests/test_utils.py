import json
from unittest.mock import MagicMock

import pytest
import requests
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


def test_parse_comma_separated_args_when_comma_separated_list_supplied_returns_list_of_string() -> (
    None
):
    assert utils.parse_comma_separated_args("test1,test2,test3") == [
        "test1",
        "test2",
        "test3",
    ]


def test_get_test_payload_returns_values_for_known_types() -> None:
    for model_type in utils.ModelType:
        assert isinstance(utils.ModelType.get_test_payload(model_type.name), dict)


def test_get_test_payload_score_contains_required_fields() -> None:
    payload = utils.ModelType.get_test_payload(utils.ModelType.score.name)
    expected_payload = {"encoding_format": "float", "text_1": "Test", "text_2": "Test2"}
    assert expected_payload.items() <= payload.items()


def test_get_all_fields_returns_list_of_strings() -> None:
    fields = utils.ModelType.get_all_fields()
    assert isinstance(fields, list)
    assert isinstance(fields[0], str)


def test_is_model_healthy_when_requests_responds_with_status_code_200_returns_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_mock = MagicMock(return_value=MagicMock(status_code=200))
    monkeypatch.setattr("requests.post", request_mock)
    assert utils.is_model_healthy("http://localhost", "test", "chat") is True


def test_is_model_healthy_when_requests_raises_exception_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_mock = MagicMock(side_effect=requests.exceptions.ReadTimeout)
    monkeypatch.setattr("requests.post", request_mock)
    assert utils.is_model_healthy("http://localhost", "test", "chat") is False


def test_is_model_healthy_when_requests_status_with_status_code_not_200_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    # Mock an internal server error response
    mock_response = MagicMock(status_code=500)

    # Tell the mock to raise an HTTP Error when raise_for_status() is called
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError

    request_mock = MagicMock(return_value=mock_response)
    monkeypatch.setattr("requests.post", request_mock)

    assert utils.is_model_healthy("http://localhost", "test", "chat") is False


def test_is_model_healthy_includes_api_key_header_when_env_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that VLLM_API_KEY env var is included as Authorization header."""
    monkeypatch.setenv("VLLM_API_KEY", "test-secret-key")
    request_mock = MagicMock(return_value=MagicMock(status_code=200))
    monkeypatch.setattr("requests.post", request_mock)

    assert utils.is_model_healthy("http://localhost", "test", "chat") is True

    # Verify Authorization header was included
    call_kwargs = request_mock.call_args
    headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
    assert "Authorization" in headers
    assert headers["Authorization"] == "Bearer test-secret-key"


def test_is_model_healthy_no_auth_header_when_env_not_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that no Authorization header is sent when VLLM_API_KEY is not set."""
    monkeypatch.delenv("VLLM_API_KEY", raising=False)
    request_mock = MagicMock(return_value=MagicMock(status_code=200))
    monkeypatch.setattr("requests.post", request_mock)

    assert utils.is_model_healthy("http://localhost", "test", "chat") is True

    # Verify no Authorization header was included
    call_kwargs = request_mock.call_args
    headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
    assert "Authorization" not in headers


def test_is_model_healthy_transcription_includes_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that VLLM_API_KEY is included for transcription health checks."""
    monkeypatch.setenv("VLLM_API_KEY", "test-key")
    request_mock = MagicMock(return_value=MagicMock(status_code=200))
    monkeypatch.setattr("requests.post", request_mock)

    assert utils.is_model_healthy("http://localhost", "test", "transcription") is True

    call_kwargs = request_mock.call_args
    headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
    assert headers is not None
    assert headers["Authorization"] == "Bearer test-key"
