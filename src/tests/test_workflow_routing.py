# Copyright 2024-2025 The vLLM Production Stack Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for workflow-aware routing."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock
import time

from vllm_router.models.workflow import WorkflowMetadata, WorkflowContext, AgentMessage
from vllm_router.services.workflow_service import WorkflowContextManager, WorkflowMessageQueue
from vllm_router.routers.workflow_aware_router import WorkflowAwareRouter
from vllm_router.service_discovery import EndpointInfo
from fastapi import Request


class TestWorkflowMetadata:
    """Test workflow metadata models."""
    
    def test_workflow_metadata_creation(self):
        """Test creating workflow metadata."""
        metadata = WorkflowMetadata(
            workflow_id="test-workflow-123",
            agent_id="agent-1",
            parent_request_id="req-456",
            workflow_priority=2.0,
            context_sharing_strategy="broadcast"
        )
        
        assert metadata.workflow_id == "test-workflow-123"
        assert metadata.agent_id == "agent-1"
        assert metadata.parent_request_id == "req-456"
        assert metadata.workflow_priority == 2.0
        assert metadata.context_sharing_strategy == "broadcast"
    
    def test_workflow_context(self):
        """Test workflow context operations."""
        context = WorkflowContext(workflow_id="test-workflow")
        
        # Test agent registration
        context.register_agent("agent-1")
        context.register_agent("agent-2")
        
        assert len(context.active_agents) == 2
        assert "agent-1" in context.active_agents
        assert "agent-2" in context.active_agents
        
        # Test stats update
        context.update_stats(cache_hit=True, tokens=100)
        context.update_stats(cache_hit=False, tokens=50)
        
        assert context.total_requests == 2
        assert context.cache_hits == 1
        assert context.total_tokens == 150
        assert context.get_cache_hit_rate() == 0.5
        
        # Test activity check
        assert context.is_active(ttl=3600)
        
        # Simulate old context
        context.last_updated = time.time() - 7200  # 2 hours ago
        assert not context.is_active(ttl=3600)


class TestWorkflowContextManager:
    """Test workflow context manager."""
    
    @pytest.mark.asyncio
    async def test_workflow_registration(self):
        """Test registering workflows."""
        manager = WorkflowContextManager(ttl=3600, max_workflows=10)
        
        metadata = WorkflowMetadata(workflow_id="test-123")
        context = await manager.register_workflow("test-123", metadata)
        
        assert context.workflow_id == "test-123"
        assert manager.total_workflows_created == 1
        
        # Test getting existing workflow
        existing = await manager.get_workflow("test-123")
        assert existing is not None
        assert existing.workflow_id == "test-123"
        
        # Test non-existent workflow
        none_workflow = await manager.get_workflow("non-existent")
        assert none_workflow is None
    
    @pytest.mark.asyncio
    async def test_instance_assignment(self):
        """Test instance assignment logic."""
        manager = WorkflowContextManager()
        
        # Register workflow
        metadata = WorkflowMetadata(workflow_id="test-123")
        await manager.register_workflow("test-123", metadata)
        
        # Test assignment
        instances = ["http://vllm-1:8000", "http://vllm-2:8000", "http://vllm-3:8000"]
        
        assigned1 = await manager.assign_instance("test-123", "agent-1", instances)
        assert assigned1 in instances
        
        # Same workflow should get same instance
        assigned2 = await manager.assign_instance("test-123", "agent-2", instances)
        assert assigned2 == assigned1
        
        # Test with load information
        loads = {
            "http://vllm-1:8000": 0.8,
            "http://vllm-2:8000": 0.2,
            "http://vllm-3:8000": 0.5
        }
        
        # New workflow should prefer low-load instance
        assigned3 = await manager.assign_instance("test-456", None, instances, loads)
        assert assigned3 == "http://vllm-2:8000"
    
    @pytest.mark.asyncio
    async def test_workflow_cleanup(self):
        """Test expired workflow cleanup."""
        manager = WorkflowContextManager(ttl=1, cleanup_interval=1)
        
        # Register workflow
        metadata = WorkflowMetadata(workflow_id="test-123")
        await manager.register_workflow("test-123", metadata)
        
        # Start cleanup task
        await manager.start()
        
        # Workflow should exist
        assert await manager.get_workflow("test-123") is not None
        
        # Wait for TTL to expire
        await asyncio.sleep(2)
        
        # Workflow should be cleaned up
        assert await manager.get_workflow("test-123") is None
        assert manager.total_workflows_expired >= 1
        
        await manager.stop()


class TestWorkflowMessageQueue:
    """Test agent message queue."""
    
    @pytest.mark.asyncio
    async def test_message_send_receive(self):
        """Test sending and receiving messages."""
        queue = WorkflowMessageQueue(max_queue_size=10)
        
        # Create and send message
        message = AgentMessage(
            workflow_id="test-workflow",
            source_agent="agent-1",
            target_agent="agent-2",
            payload={"data": "test message"}
        )
        
        success = await queue.send_message(message)
        assert success
        assert queue.total_messages_sent == 1
        
        # Receive message
        messages = await queue.receive_messages("test-workflow", "agent-2", timeout=1.0)
        assert len(messages) == 1
        assert messages[0].payload["data"] == "test message"
        assert queue.total_messages_received == 1
        
        # No messages for different agent
        no_messages = await queue.receive_messages("test-workflow", "agent-3", timeout=0.1)
        assert len(no_messages) == 0
    
    @pytest.mark.asyncio
    async def test_message_expiration(self):
        """Test message expiration."""
        queue = WorkflowMessageQueue()
        
        # Create expired message
        message = AgentMessage(
            workflow_id="test-workflow",
            source_agent="agent-1",
            target_agent="agent-2",
            payload={"data": "expired"},
            ttl=0  # Expires immediately
        )
        
        await queue.send_message(message)
        
        # Should not receive expired message
        messages = await queue.receive_messages("test-workflow", "agent-2", timeout=0.1)
        assert len(messages) == 0
    
    @pytest.mark.asyncio
    async def test_queue_full(self):
        """Test queue full behavior."""
        queue = WorkflowMessageQueue(max_queue_size=2)
        
        # Fill queue
        for i in range(2):
            message = AgentMessage(
                workflow_id="test-workflow",
                source_agent="agent-1",
                target_agent="agent-2",
                payload={"data": f"message-{i}"}
            )
            success = await queue.send_message(message)
            assert success
        
        # Queue should be full
        message3 = AgentMessage(
            workflow_id="test-workflow",
            source_agent="agent-1",
            target_agent="agent-2",
            payload={"data": "message-3"}
        )
        success = await queue.send_message(message3)
        assert not success


class TestWorkflowAwareRouter:
    """Test workflow-aware router."""
    
    @pytest.mark.asyncio
    async def test_workflow_routing(self):
        """Test workflow-aware routing decisions."""
        router = WorkflowAwareRouter(
            lmcache_controller_port=9000,
            session_key="x-user-id",
            workflow_ttl=3600
        )
        
        # Mock KV manager start
        router.start_kv_manager = Mock()
        
        # Create test endpoints
        endpoints = [
            EndpointInfo(url="http://vllm-1:8000", model_names=["llama"]),
            EndpointInfo(url="http://vllm-2:8000", model_names=["llama"]),
        ]
        
        # Create mock request
        request = Mock(spec=Request)
        request.headers = {}
        
        # Test workflow routing
        request_json = {
            "model": "llama",
            "prompt": "test prompt",
            "workflow_metadata": {
                "workflow_id": "test-workflow-123",
                "agent_id": "agent-1"
            }
        }
        
        # First request should establish workflow assignment
        url1 = await router.route_request(
            endpoints, {}, {}, request, request_json
        )
        assert url1 in ["http://vllm-1:8000", "http://vllm-2:8000"]
        assert router.total_workflow_requests == 1
        
        # Second request with same workflow should route to same instance
        request_json2 = {
            "model": "llama",
            "prompt": "another prompt",
            "workflow_metadata": {
                "workflow_id": "test-workflow-123",
                "agent_id": "agent-2"
            }
        }
        
        url2 = await router.route_request(
            endpoints, {}, {}, request, request_json2
        )
        assert url2 == url1  # Should route to same instance
        assert router.total_workflow_requests == 2
    
    @pytest.mark.asyncio
    async def test_non_workflow_routing(self):
        """Test fallback to parent routing for non-workflow requests."""
        router = WorkflowAwareRouter(
            lmcache_controller_port=9000,
            session_key="x-user-id"
        )
        
        # Mock parent route_request
        parent_route_request = AsyncMock(return_value="http://vllm-1:8000")
        router.__class__.__bases__[0].route_request = parent_route_request
        
        endpoints = [
            EndpointInfo(url="http://vllm-1:8000", model_names=["llama"])
        ]
        
        request = Mock(spec=Request)
        request_json = {
            "model": "llama",
            "prompt": "test prompt"
            # No workflow_metadata
        }
        
        url = await router.route_request(
            endpoints, {}, {}, request, request_json
        )
        
        # Should fall back to parent routing
        assert parent_route_request.called
        assert router.total_workflow_requests == 0
    
    @pytest.mark.asyncio
    async def test_workflow_stats(self):
        """Test workflow statistics."""
        router = WorkflowAwareRouter(
            lmcache_controller_port=9000,
            session_key="x-user-id"
        )
        
        # Simulate some requests
        router.total_workflow_requests = 100
        router.workflow_cache_hits = 75
        router.workflow_routing_decisions = 100
        
        stats = await router.get_workflow_stats()
        
        assert stats["workflow_routing"]["total_requests"] == 100
        assert stats["workflow_routing"]["cache_hits"] == 75
        assert stats["workflow_routing"]["cache_hit_rate"] == 0.75
        assert stats["workflow_routing"]["routing_decisions"] == 100