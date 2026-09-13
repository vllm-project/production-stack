from unittest.mock import MagicMock

import pytest

from vllm_router.service_discovery import StaticServiceDiscovery


@pytest.mark.parametrize(
    ("list_name", "models", "model_labels", "model_types"),
    [
        ("models", ["m-a"], ["label-a", "label-b"], ["chat", "chat"]),
        ("model_labels", ["m-a", "m-b"], ["label-a"], ["chat", "chat"]),
        ("model_types", ["m-a", "m-b"], ["label-a", "label-b"], ["chat"]),
    ],
)
def test_init_when_index_aligned_list_lengths_differ_raises_value_error(
    list_name: str,
    models: list[str],
    model_labels: list[str],
    model_types: list[str],
) -> None:
    with pytest.raises(
        ValueError,
        match=rf"urls \(2\) and {list_name} \(1\) must have the same length",
    ):
        StaticServiceDiscovery(
            app=None,
            urls=["http://127.0.0.1:1", "http://127.0.0.1:2"],
            models=models,
            model_labels=model_labels,
            model_types=model_types,
        )


def test_init_when_models_are_missing_raises_value_error() -> None:
    with pytest.raises(ValueError, match="models must be provided"):
        StaticServiceDiscovery(
            app=None,
            urls=["http://127.0.0.1:1"],
            models=None,
        )


def test_get_unhealthy_endpoint_hashes_marks_all_endpoints_unhealthy_when_lengths_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    is_model_healthy_mock = MagicMock(return_value=False)
    monkeypatch.setattr("vllm_router.utils.is_model_healthy", is_model_healthy_mock)
    discovery_instance = StaticServiceDiscovery(
        app=None,
        urls=["http://127.0.0.1:1", "http://127.0.0.1:2"],
        models=["m-a", "m-b"],
        model_labels=["label-a", "label-b"],
        model_types=["chat", "chat"],
    )
    discovery_instance.model_types.pop()

    discovery_instance.unhealthy_endpoint_hashes = (
        discovery_instance.get_unhealthy_endpoint_hashes()
    )

    assert discovery_instance.unhealthy_endpoint_hashes == [
        discovery_instance.get_model_endpoint_hash("http://127.0.0.1:1", "m-a"),
        discovery_instance.get_model_endpoint_hash("http://127.0.0.1:2", "m-b"),
    ]
    assert discovery_instance.get_endpoint_info() == []
    is_model_healthy_mock.assert_not_called()


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

    def mock_is_model_healthy(
        url: str, model: str, model_type: str, timeout: int = 10
    ) -> bool:
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


def test_has_ever_seen_model_when_model_in_models_list_returns_true():
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
    assert discovery_instance.has_ever_seen_model("llama3") is True
    assert discovery_instance.has_ever_seen_model("unknown-model") is False


def test_has_ever_seen_model_when_model_is_alias_returns_true():
    discovery_instance = StaticServiceDiscovery(
        None,
        ["http://localhost.com"],
        ["llama3"],
        {"llama": "llama3"},
        None,
        ["chat"],
        static_backend_health_checks=False,
        prefill_model_labels=None,
        decode_model_labels=None,
    )
    assert discovery_instance.has_ever_seen_model("llama") is True
    assert discovery_instance.has_ever_seen_model("llama3") is True
    assert discovery_instance.has_ever_seen_model("unknown-model") is False
