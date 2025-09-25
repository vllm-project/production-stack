from unittest.mock import MagicMock

import pytest

from vllm_router.service_discovery import StaticServiceDiscovery


def test_init_when_static_backend_health_checks_calls_start_health_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_health_check_mock = MagicMock()
    monkeypatch.setattr(
        "vllm_router.service_discovery.StaticServiceDiscovery.start_health_check_task",
        start_health_check_mock,
    )
    discovery_instance = StaticServiceDiscovery(
        None,
        [],
        [],
        None,
        None,
        None,
        static_backend_health_checks=True,
        prefill_model_labels=None,
        decode_model_labels=None,
    )
    discovery_instance.start_health_check_task.assert_called_once()


def test_init_when_endpoint_health_check_disabled_does_not_call_start_health_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_health_check_mock = MagicMock()
    monkeypatch.setattr(
        "vllm_router.service_discovery.StaticServiceDiscovery.start_health_check_task",
        start_health_check_mock,
    )
    discovery_instance = StaticServiceDiscovery(
        None,
        [],
        [],
        None,
        None,
        None,
        static_backend_health_checks=False,
        prefill_model_labels=None,
        decode_model_labels=None,
    )
    discovery_instance.start_health_check_task.assert_not_called()


def test_get_unhealthy_endpoint_hashes_when_only_healthy_models_exist_does_not_return_unhealthy_endpoint_hashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("vllm_router.utils.is_model_healthy", lambda *_: True)
    discovery_instance = StaticServiceDiscovery(
        None,
        ["http://localhost.com"],
        ["llama3"],
        None,
        None,
        ["chat"],
        static_backend_health_checks=True,
        prefill_model_labels=None,
        decode_model_labels=None,
    )
    assert discovery_instance.get_unhealthy_endpoint_hashes() == []


def test_get_unhealthy_endpoint_hashes_when_unhealthy_model_exist_returns_unhealthy_endpoint_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("vllm_router.utils.is_model_healthy", lambda *_: False)
    discovery_instance = StaticServiceDiscovery(
        None,
        ["http://localhost.com"],
        ["llama3"],
        None,
        None,
        ["chat"],
        static_backend_health_checks=False,
        prefill_model_labels=None,
        decode_model_labels=None,
    )
    assert discovery_instance.get_unhealthy_endpoint_hashes() == [
        "ee7d421a744e07595b70f98c11be93e7"
    ]


def test_get_unhealthy_endpoint_hashes_when_healthy_and_unhealthy_models_exist_returns_only_unhealthy_endpoint_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unhealthy_model = "bge-m3"

    def mock_is_model_healthy(url: str, model: str, model_type: str) -> bool:
        return model != unhealthy_model

    monkeypatch.setattr("vllm_router.utils.is_model_healthy", mock_is_model_healthy)
    discovery_instance = StaticServiceDiscovery(
        None,
        ["http://localhost.com", "http://10.123.112.412"],
        ["llama3", unhealthy_model],
        None,
        None,
        ["chat", "embeddings"],
        static_backend_health_checks=False,
        prefill_model_labels=None,
        decode_model_labels=None,
    )
    assert discovery_instance.get_unhealthy_endpoint_hashes() == [
        "01e1b07eca36d39acacd55a33272a225"
    ]


def test_get_endpoint_info_when_model_endpoint_hash_is_in_unhealthy_endpoint_does_not_return_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unhealthy_model = "mistral"

    def mock_get_model_endpoint_hash(url: str, model: str) -> str:
        return "some-hash" if model == unhealthy_model else "other-hash"

    discovery_instance = StaticServiceDiscovery(
        None,
        ["http://localhost.com", "http://10.123.112.412"],
        ["llama3", unhealthy_model],
        None,
        None,
        ["chat", "chat"],
        static_backend_health_checks=False,
        prefill_model_labels=None,
        decode_model_labels=None,
    )
    discovery_instance.unhealthy_endpoint_hashes = ["some-hash"]
    monkeypatch.setattr(
        discovery_instance, "get_model_endpoint_hash", mock_get_model_endpoint_hash
    )
    assert len(discovery_instance.get_endpoint_info()) == 1
    assert "llama3" in discovery_instance.get_endpoint_info()[0].model_names
