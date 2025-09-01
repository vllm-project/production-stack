#!/usr/bin/env python3
"""
Unit tests for Swagger UI integration with Pydantic models.
Tests the OpenAI-compatible API endpoints with automatic validation.
"""

import sys
import os
import pytest
import json
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.testclient import TestClient

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Mock dependencies that might not be available in test environment
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

# Mock modules before importing our code
sys.modules['vllm_router.service_discovery'] = type('MockModule', (), {
    'get_service_discovery': lambda: MockServiceDiscovery()
})()

sys.modules['vllm_router.stats.engine_stats'] = type('MockModule', (), {
    'get_engine_stats_scraper': lambda: MockEngineStatsScraper()
})()

sys.modules['vllm_router.dynamic_config'] = type('MockModule', (), {
    'get_dynamic_config_watcher': lambda: MockDynamicConfigWatcher()
})()

sys.modules['vllm_router.version'] = type('MockModule', (), {
    '__version__': '1.0.0'
})()

# Create mock for request service
class MockRequestModule:
    @staticmethod
    async def route_general_request(request, endpoint, background_tasks, request_body=None):
        """Mock implementation that mimics the real route_general_request function"""
        if request_body:
            data = json.loads(request_body)
        else:
            data = await request.json()
        
        return {
            "mock_response": True,
            "endpoint": endpoint,
            "model": data.get("model"),
            "request_type": "pydantic" if request_body else "raw",
            "data": data
        }
    
    @staticmethod
    def route_sleep_wakeup_request(r, e, b):
        return {"sleep": True}

sys.modules['vllm_router.services.request_service.request'] = MockRequestModule()

# Now import our router after mocking
from vllm_router.routers.main_router import main_router

# Create test app and client
app = FastAPI()
app.include_router(main_router)
client = TestClient(app)


class TestSwaggerIntegration:
    """Test Swagger UI integration with Pydantic models"""

    def test_chat_completions_pydantic_model(self):
        """Test /v1/chat/completions with Pydantic model validation"""
        response = client.post("/v1/chat/completions", json={
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 100,
            "temperature": 0.7
        })
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["mock_response"] == True
        assert data["endpoint"] == "/v1/chat/completions"
        assert data["model"] == "gpt-3.5-turbo"
        assert data["request_type"] == "pydantic"

    def test_completions_pydantic_model(self):
        """Test /v1/completions with Pydantic model validation"""
        response = client.post("/v1/completions", json={
            "model": "gpt-3.5-turbo",
            "prompt": "Hello world",
            "max_tokens": 50
        })
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["mock_response"] == True
        assert data["endpoint"] == "/v1/completions"
        assert data["model"] == "gpt-3.5-turbo"
        assert data["request_type"] == "pydantic"

    def test_embeddings_pydantic_model(self):
        """Test /v1/embeddings with Pydantic model validation"""
        response = client.post("/v1/embeddings", json={
            "model": "text-embedding-ada-002",
            "input": "Hello world"
        })
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["mock_response"] == True
        assert data["endpoint"] == "/v1/embeddings"
        assert data["model"] == "text-embedding-ada-002"
        assert data["request_type"] == "pydantic"

    def test_extra_fields_handling(self):
        """Test that extra fields are logged but don't break the request"""
        response = client.post("/v1/chat/completions", json={
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 100,
            "unknown_field": "should be ignored"
        })
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["mock_response"] == True
        assert data["request_type"] == "pydantic"


class TestSemanticCacheCompatibility:
    """Test semantic cache compatibility with Pydantic models"""
    
    def test_semantic_cache_uses_raw_request(self):
        """
        Test that semantic cache functionality still uses raw_request correctly.
        This verifies that the check_semantic_cache function receives the proper
        raw Request object, not the parsed Pydantic model.
        """
        # Mock the semantic cache to track what request object it receives
        original_available = hasattr(sys.modules.get('vllm_router.routers.main_router'), 'semantic_cache_available')
        
        # Create a test that will track the request type passed to semantic cache
        received_request_type = None
        
        async def mock_check_semantic_cache(request):
            nonlocal received_request_type
            received_request_type = type(request).__name__
            # Return None to continue with normal processing
            return None
        
        # Patch the semantic cache check function
        import vllm_router.routers.main_router as router_module
        if hasattr(router_module, 'check_semantic_cache'):
            original_check = router_module.check_semantic_cache
            router_module.check_semantic_cache = mock_check_semantic_cache
            router_module.semantic_cache_available = True
            
            try:
                # Make a request that would trigger semantic cache check
                response = client.post("/v1/chat/completions", json={
                    "model": "gpt-3.5-turbo",
                    "messages": [{"role": "user", "content": "Hello cache test"}],
                    "max_tokens": 100
                })
                
                # Verify the request succeeded
                assert response.status_code == 200
                
                # Verify that semantic cache received a Request object, not a Pydantic model
                assert received_request_type == "Request", f"Expected 'Request', got '{received_request_type}'"
                
            finally:
                # Restore original function
                router_module.check_semantic_cache = original_check
                if not original_available:
                    router_module.semantic_cache_available = False
        else:
            # If semantic cache is not available, just verify the request works
            response = client.post("/v1/chat/completions", json={
                "model": "gpt-3.5-turbo", 
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 100
            })
            assert response.status_code == 200
    
    def test_semantic_cache_with_pydantic_request_body(self):
        """
        Test that when semantic cache is bypassed, the Pydantic request body
        is properly converted and passed to the backend service.
        """
        response = client.post("/v1/chat/completions", json={
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "Test message"}],
            "max_tokens": 100,
            "temperature": 0.7,
            "cache_similarity_threshold": 0.9  # Semantic cache specific field
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["mock_response"] == True
        assert data["request_type"] == "pydantic"
        
        # Verify that semantic cache specific fields are preserved in the request
        request_data = data["data"]
        assert "cache_similarity_threshold" in request_data
        assert request_data["cache_similarity_threshold"] == 0.9


class TestBackwardCompatibility:
    """Test backward compatibility with existing functionality"""

    def test_validation_errors(self):
        """Test that Pydantic validation catches invalid requests"""
        # Missing required field (model)
        response = client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "Hello"}]
        })
        
        assert response.status_code == 422  # FastAPI validation error
        error_data = response.json()
        assert "detail" in error_data
        assert any("model" in str(error).lower() for error in error_data["detail"])

    def test_invalid_json(self):
        """Test handling of invalid JSON"""
        response = client.post(
            "/v1/chat/completions", 
            data="invalid json",
            headers={"Content-Type": "application/json"}
        )
        
        assert response.status_code == 422  # FastAPI validation error

    def test_openapi_schema_generation(self):
        """Test that OpenAPI schema is generated correctly"""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        
        schema = response.json()
        assert "paths" in schema
        
        # Check that our endpoints are in the schema
        paths = schema["paths"]
        assert "/v1/chat/completions" in paths
        assert "/v1/completions" in paths
        assert "/v1/embeddings" in paths
        
        # Check that request models are properly defined
        chat_completions = paths["/v1/chat/completions"]["post"]
        assert "requestBody" in chat_completions
        request_body = chat_completions["requestBody"]["content"]["application/json"]
        assert "$ref" in request_body["schema"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
