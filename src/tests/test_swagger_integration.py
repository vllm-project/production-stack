#!/usr/bin/env python3
"""Unit tests for Swagger UI integration: request validation & OpenAPI generation."""

import json
import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class MockServiceDiscovery:
    def get_endpoint_info(self):
        return []

    def get_health(self):
        return True


class MockEngineStatsScraper:
    def get_health(self):
        return True


class MockDynamicConfigWatcher:
    def get_current_config(self):
        class MockConfig:
            def to_json_str(self):
                return '{"mock": true}'

        return MockConfig()


sys.modules["vllm_router.service_discovery"] = type(
    "MockModule", (), {"get_service_discovery": lambda: MockServiceDiscovery()}
)()
sys.modules["vllm_router.stats.engine_stats"] = type(
    "MockModule", (), {"get_engine_stats_scraper": lambda: MockEngineStatsScraper()}
)()
sys.modules["vllm_router.dynamic_config"] = type(
    "MockModule", (), {"get_dynamic_config_watcher": lambda: MockDynamicConfigWatcher()}
)()
sys.modules["vllm_router.version"] = type("MockModule", (), {"__version__": "1.0.0"})()


class MockRequestModule:
    @staticmethod
    async def route_general_request(
        request, endpoint, background_tasks, request_body=None
    ):
        if request_body:
            data = json.loads(request_body)
        else:
            data = await request.json()
        return {
            "mock_response": True,
            "endpoint": endpoint,
            "model": data.get("model"),
            "request_type": "pydantic" if request_body else "raw",
            "data": data,
        }

    @staticmethod
    def route_sleep_wakeup_request(r, e, b):  # pragma: no cover
        return {"sleep": True}


sys.modules["vllm_router.services.request_service.request"] = MockRequestModule()

from vllm_router.routers.main_router import main_router  # noqa: E402

app = FastAPI()
app.include_router(main_router)
client = TestClient(app)


class TestSwaggerIntegration:
    def test_chat_completions_pydantic_model(self):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 100,
                "temperature": 0.7,
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mock_response"]
        assert data["endpoint"] == "/v1/chat/completions"
        assert data["model"] == "gpt-3.5-turbo"
        assert data["request_type"] == "pydantic"

    def test_completions_pydantic_model(self):
        resp = client.post(
            "/v1/completions",
            json={"model": "gpt-3.5-turbo", "prompt": "Hello world", "max_tokens": 50},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mock_response"]
        assert data["endpoint"] == "/v1/completions"
        assert data["model"] == "gpt-3.5-turbo"
        assert data["request_type"] == "pydantic"

    def test_embeddings_pydantic_model(self):
        resp = client.post(
            "/v1/embeddings",
            json={"model": "text-embedding-ada-002", "input": "Hello world"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mock_response"]
        assert data["endpoint"] == "/v1/embeddings"
        assert data["model"] == "text-embedding-ada-002"
        assert data["request_type"] == "pydantic"

    def test_extra_fields_handling(self):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 100,
                "unknown_field": "ignored",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mock_response"]
        assert data["request_type"] == "pydantic"


class TestSemanticCacheCompatibility:
    def test_semantic_cache_uses_raw_request(self):
        import vllm_router.routers.main_router as router_module

        received_request_type = None

        async def mock_check_semantic_cache(request):
            nonlocal received_request_type
            received_request_type = type(request).__name__
            return None

        if hasattr(router_module, "check_semantic_cache"):
            original_check = router_module.check_semantic_cache
            original_flag = getattr(router_module, "semantic_cache_available", False)
            router_module.check_semantic_cache = mock_check_semantic_cache
            router_module.semantic_cache_available = True
            try:
                resp = client.post(
                    "/v1/chat/completions",
                    json={
                        "model": "gpt-3.5-turbo",
                        "messages": [{"role": "user", "content": "Cache test"}],
                    },
                )
                assert resp.status_code == 200
                assert received_request_type == "Request"
            finally:
                router_module.check_semantic_cache = original_check
                router_module.semantic_cache_available = original_flag
        else:
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-3.5-turbo",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
            )
            assert resp.status_code == 200

    def test_semantic_cache_with_pydantic_request_body(self):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "Test message"}],
                "cache_similarity_threshold": 0.9,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mock_response"]
        assert data["request_type"] == "pydantic"
        assert "cache_similarity_threshold" in data["data"]
        assert data["data"]["cache_similarity_threshold"] == 0.9


class TestBackwardCompatibility:
    def test_validation_errors(self):
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
        assert resp.status_code == 422
        error_data = resp.json()
        assert "detail" in error_data
        assert any("model" in str(err).lower() for err in error_data["detail"])

    def test_invalid_json(self):
        resp = client.post(
            "/v1/chat/completions",
            data="invalid json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_openapi_schema_generation(self):
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert "paths" in schema
        paths = schema["paths"]
        for p in ["/v1/chat/completions", "/v1/completions", "/v1/embeddings"]:
            assert p in paths
        chat_post = paths["/v1/chat/completions"]["post"]
        assert "requestBody" in chat_post
        rb = chat_post["requestBody"]["content"]["application/json"]
        assert "$ref" in rb["schema"]


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
