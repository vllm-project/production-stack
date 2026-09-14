from vllm_router.services.request_service.request import (
    _resolve_timeout_seconds,
)


class TestResolveTimeoutSeconds:
    def test_env_unset_returns_default(self, monkeypatch):
        monkeypatch.delenv("ROUTER_DECODE_TIMEOUT_SECONDS", raising=False)
        assert _resolve_timeout_seconds("ROUTER_DECODE_TIMEOUT_SECONDS", 600) == 600

    def test_env_unset_none_default(self, monkeypatch):
        monkeypatch.delenv("ROUTER_PROXY_TIMEOUT_SECONDS", raising=False)
        assert _resolve_timeout_seconds("ROUTER_PROXY_TIMEOUT_SECONDS", None) is None

    def test_env_value_used(self, monkeypatch):
        monkeypatch.setenv("ROUTER_DECODE_TIMEOUT_SECONDS", "900")
        assert _resolve_timeout_seconds("ROUTER_DECODE_TIMEOUT_SECONDS", 600) == 900

    def test_env_float_value(self, monkeypatch):
        monkeypatch.setenv("ROUTER_PREFILL_TIMEOUT_SECONDS", "42.5")
        assert _resolve_timeout_seconds("ROUTER_PREFILL_TIMEOUT_SECONDS", 300) == 42.5

    def test_empty_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("ROUTER_DECODE_TIMEOUT_SECONDS", "  ")
        assert _resolve_timeout_seconds("ROUTER_DECODE_TIMEOUT_SECONDS", 600) == 600

    def test_non_numeric_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("ROUTER_DECODE_TIMEOUT_SECONDS", "abc")
        assert _resolve_timeout_seconds("ROUTER_DECODE_TIMEOUT_SECONDS", 600) == 600

    def test_negative_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("ROUTER_DECODE_TIMEOUT_SECONDS", "-10")
        assert _resolve_timeout_seconds("ROUTER_DECODE_TIMEOUT_SECONDS", 600) == 600

    def test_non_finite_env_falls_back_to_default(self, monkeypatch):
        for raw in ("nan", "inf", "-inf"):
            monkeypatch.setenv("ROUTER_DECODE_TIMEOUT_SECONDS", raw)
            assert _resolve_timeout_seconds("ROUTER_DECODE_TIMEOUT_SECONDS", 600) == 600

    def test_zero_is_valid(self, monkeypatch):
        monkeypatch.setenv("ROUTER_DECODE_TIMEOUT_SECONDS", "0")
        assert _resolve_timeout_seconds("ROUTER_DECODE_TIMEOUT_SECONDS", 600) == 0
