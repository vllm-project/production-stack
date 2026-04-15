"""
Tests for src/vllm_router/external_providers/
Covers: models.py, base.py, registry.py
"""

from unittest.mock import AsyncMock

import pytest

from vllm_router.external_providers.base import (
    ExternalProviderAdapter,
    ExternalProviderResponse,
)
from vllm_router.external_providers.models import (
    ExternalModelConfig,
    ExternalProviderConfig,
)
from vllm_router.external_providers.openai_provider import OpenAIProvider
from vllm_router.external_providers.registry import (
    ADAPTER_REGISTRY,
    ExternalProviderManager,
)

from .conftest import make_provider_config

# ---------------------------------------------------------------------------
# Stub concrete adapter (used in ABC tests)
# ---------------------------------------------------------------------------


class _StubAdapter(ExternalProviderAdapter):
    async def send_request(self, endpoint, payload, stream=False):
        pass

    async def health_check(self):
        return True

    async def close(self):
        pass

    async def fetch_available_model_ids(self):
        return []


# ---------------------------------------------------------------------------
# models.py
# ---------------------------------------------------------------------------


class TestExternalModelConfig:
    def test_from_dict_minimal(self):
        m = ExternalModelConfig.from_dict({"id": "gpt-4o"})
        assert m.id == "gpt-4o"
        assert m.type == "chat"
        assert m.aliases == []

    def test_from_dict_full(self):
        m = ExternalModelConfig.from_dict(
            {"id": "gpt-4o", "type": "embedding", "aliases": ["gpt4o", "gpt-4"]}
        )
        assert m.id == "gpt-4o"
        assert m.type == "embedding"
        assert m.aliases == ["gpt4o", "gpt-4"]


class TestExternalProviderConfig:
    def test_from_dict_minimal(self):
        cfg = ExternalProviderConfig.from_dict(
            {"name": "openai", "type": "openai", "api_base": "https://api.openai.com"}
        )
        assert cfg.name == "openai"
        assert cfg.type == "openai"
        assert cfg.api_base == "https://api.openai.com"
        assert cfg.models == []
        assert cfg.timeout == 30.0
        assert cfg.max_retries == 3
        assert cfg.custom_headers == {}

    def test_from_dict_full(self):
        cfg = ExternalProviderConfig.from_dict(
            {
                "name": "openai",
                "type": "openai",
                "api_base": "https://api.openai.com",
                "models": [{"id": "gpt-4o", "aliases": ["gpt4o"]}],
                "api_key_env_var": "OPENAI_KEY",
                "timeout": 20.0,
                "max_retries": 5,
                "custom_headers": {"X-Custom": "value"},
            }
        )
        assert cfg.api_key_env_var == "OPENAI_KEY"
        assert cfg.timeout == 20.0
        assert cfg.max_retries == 5
        assert cfg.custom_headers == {"X-Custom": "value"}
        assert len(cfg.models) == 1
        assert cfg.models[0].aliases == ["gpt4o"]

    def test_get_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("MY_API_KEY", "sk-test-123")
        cfg = make_provider_config(api_key_env_var="MY_API_KEY")
        assert cfg.get_api_key() == "sk-test-123"

    def test_get_api_key_uses_default_env_var(self, monkeypatch):
        monkeypatch.setenv("DEFAULT_KEY", "sk-default")
        cfg = make_provider_config(api_key_env_var=None)
        assert cfg.get_api_key(default_env_var="DEFAULT_KEY") == "sk-default"

    def test_get_api_key_returns_none_when_no_env_var(self):
        cfg = make_provider_config(api_key_env_var=None)
        assert cfg.get_api_key() is None

    def test_get_api_key_raises_when_env_var_missing(self, monkeypatch):
        monkeypatch.delenv("MISSING_KEY", raising=False)
        cfg = make_provider_config(api_key_env_var="MISSING_KEY")
        with pytest.raises(ValueError, match="MISSING_KEY"):
            cfg.get_api_key()

    def test_get_all_model_ids_includes_aliases(self):
        cfg = make_provider_config(
            models=[
                ExternalModelConfig(id="gpt-4o", aliases=["gpt4o", "gpt-4"]),
                ExternalModelConfig(id="gpt-3.5-turbo"),
            ]
        )
        assert set(cfg.get_all_model_ids()) == {
            "gpt-4o",
            "gpt4o",
            "gpt-4",
            "gpt-3.5-turbo",
        }

    @pytest.mark.parametrize(
        "requested, expected",
        [
            ("gpt-4o", "gpt-4o"),  # canonical
            ("gpt4o", "gpt-4o"),  # alias
            ("gpt-4", "gpt-4o"),  # second alias
        ],
    )
    def test_resolve_model_id(self, requested, expected):
        cfg = make_provider_config(
            models=[ExternalModelConfig(id="gpt-4o", aliases=["gpt4o", "gpt-4"])]
        )
        assert cfg.resolve_model_id(requested) == expected

    def test_resolve_model_id_not_found(self):
        cfg = make_provider_config(models=[ExternalModelConfig(id="gpt-4o")])
        assert cfg.resolve_model_id("unknown-model") is None


# ---------------------------------------------------------------------------
# base.py
# ---------------------------------------------------------------------------


class TestExternalProviderResponse:
    def test_defaults(self):
        r = ExternalProviderResponse(status_code=200)
        assert r.status_code == 200
        assert r.headers == {}
        assert r.body is None
        assert r.is_stream is False
        assert r.stream_iterator is None


class TestExternalProviderAdapterABC:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            ExternalProviderAdapter(make_provider_config())  # type: ignore[abstract]

    def test_get_provider_name(self):
        adapter = _StubAdapter(make_provider_config(name="my-provider"))
        assert adapter.get_provider_name() == "my-provider"


# ---------------------------------------------------------------------------
# registry.py
# ---------------------------------------------------------------------------


class TestAdapterRegistry:
    def test_openai_adapter_is_registered(self):
        assert ADAPTER_REGISTRY.get("openai") is OpenAIProvider


@pytest.fixture
def manager():
    return ExternalProviderManager()


@pytest.fixture
def openai_config(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    return make_provider_config(
        name="openai",
        type_="openai",
        api_base="https://api.openai.com",
        models=[
            ExternalModelConfig(id="gpt-4o", aliases=["gpt4o"]),
            ExternalModelConfig(id="gpt-3.5-turbo"),
        ],
        api_key_env_var="OPENAI_API_KEY",
    )


@pytest.fixture
def registered_manager(manager, openai_config):
    manager.register(openai_config)
    return manager


class TestExternalProviderManagerRegister:
    def test_indexes_all_models_and_aliases(self, manager, openai_config):
        manager.register(openai_config)

        assert "openai" in manager.get_registered_providers()
        assert manager.is_external_model("gpt-4o")
        assert manager.is_external_model("gpt4o")  # alias
        assert manager.is_external_model("gpt-3.5-turbo")

    def test_unknown_type_raises(self, manager):
        with pytest.raises(ValueError, match="nonexistent-type"):
            manager.register(make_provider_config(type_="nonexistent-type"))

    def test_conflicting_model_id_across_providers_raises(self, manager, monkeypatch):
        monkeypatch.setenv("KEY_A", "sk-a")
        monkeypatch.setenv("KEY_B", "sk-b")
        manager.register(
            make_provider_config(
                name="provider-a",
                models=[ExternalModelConfig(id="shared-model")],
                api_key_env_var="KEY_A",
            )
        )
        with pytest.raises(ValueError, match="shared-model"):
            manager.register(
                make_provider_config(
                    name="provider-b",
                    models=[ExternalModelConfig(id="shared-model")],
                    api_key_env_var="KEY_B",
                )
            )


class TestExternalProviderManagerLookup:
    def test_lookup_adapter_by_canonical_id(self, registered_manager):
        assert isinstance(registered_manager.lookup_adapter("gpt-4o"), OpenAIProvider)

    def test_lookup_adapter_alias_returns_same_instance(self, registered_manager):
        assert registered_manager.lookup_adapter(
            "gpt4o"
        ) is registered_manager.lookup_adapter("gpt-4o")

    def test_lookup_adapter_unknown_returns_none(self, registered_manager):
        assert registered_manager.lookup_adapter("unknown-model") is None

    @pytest.mark.parametrize(
        "model_id, canonical",
        [("gpt-4o", "gpt-4o"), ("gpt4o", "gpt-4o")],
    )
    def test_get_canonical_model_id(self, registered_manager, model_id, canonical):
        assert registered_manager.get_canonical_model_id(model_id) == canonical

    @pytest.mark.parametrize("model_id", ["gpt-4o", "gpt4o"])
    def test_get_provider_name(self, registered_manager, model_id):
        assert registered_manager.get_provider_name(model_id) == "openai"

    def test_get_all_external_model_ids(self, registered_manager):
        assert set(registered_manager.get_all_external_model_ids()) == {
            "gpt-4o",
            "gpt4o",
            "gpt-3.5-turbo",
        }


class TestExternalProviderManagerValidateModels:
    @pytest.mark.asyncio
    async def test_removes_unavailable_models(self, registered_manager):
        registered_manager.lookup_adapter("gpt-4o").fetch_available_model_ids = (
            AsyncMock(return_value=["gpt-4o"])  # gpt-3.5-turbo absent
        )
        await registered_manager.validate_models()

        assert registered_manager.is_external_model("gpt-4o")
        assert not registered_manager.is_external_model("gpt-3.5-turbo")

    @pytest.mark.asyncio
    async def test_removes_alias_when_canonical_is_unavailable(
        self, registered_manager
    ):
        registered_manager.lookup_adapter("gpt-4o").fetch_available_model_ids = (
            AsyncMock(return_value=["gpt-3.5-turbo"])
        )
        await registered_manager.validate_models()

        assert not registered_manager.is_external_model("gpt-4o")
        assert not registered_manager.is_external_model("gpt4o")
        assert registered_manager.is_external_model("gpt-3.5-turbo")

    @pytest.mark.asyncio
    async def test_keeps_all_models_when_fetch_returns_empty(self, registered_manager):
        registered_manager.lookup_adapter("gpt-4o").fetch_available_model_ids = (
            AsyncMock(return_value=[])  # empty list → skip validation
        )
        await registered_manager.validate_models()

        assert registered_manager.is_external_model("gpt-4o")
        assert registered_manager.is_external_model("gpt-3.5-turbo")


class TestExternalProviderManagerHealthCheck:
    @pytest.mark.asyncio
    async def test_aggregates_healthy_results(self, registered_manager):
        registered_manager.lookup_adapter("gpt-4o").health_check = AsyncMock(
            return_value=True
        )
        assert await registered_manager.health_check() == {"openai": True}

    @pytest.mark.asyncio
    async def test_records_false_on_adapter_exception(self, registered_manager):
        registered_manager.lookup_adapter("gpt-4o").health_check = AsyncMock(
            side_effect=RuntimeError("boom")
        )
        assert await registered_manager.health_check() == {"openai": False}


class TestExternalProviderManagerClose:
    @pytest.mark.asyncio
    async def test_calls_close_on_each_adapter(self, registered_manager):
        adapter = registered_manager.lookup_adapter("gpt-4o")
        adapter.close = AsyncMock()

        await registered_manager.close()

        adapter.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_clears_internal_state_after_close(self, registered_manager):
        registered_manager.lookup_adapter("gpt-4o").close = AsyncMock()

        await registered_manager.close()

        assert len(registered_manager) == 0
        assert registered_manager.get_all_external_model_ids() == []

    @pytest.mark.asyncio
    async def test_continues_closing_other_adapters_on_error(self, registered_manager):
        registered_manager.lookup_adapter("gpt-4o").close = AsyncMock(
            side_effect=RuntimeError("close failed")
        )
        await registered_manager.close()  # must not raise
