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

"""Integration tests for workflow API endpoints."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

from vllm_router.routers.workflow_router import router as workflow_router
from vllm_router.services.workflow_service import WorkflowContextManager, WorkflowMessageQueue
from vllm_router.routers.workflow_aware_router import WorkflowAwareRouter
from vllm_router.models.workflow import WorkflowMetadata


@pytest.fixture
def app():
    """Create test FastAPI app with workflow router."""
    app = FastAPI()
    app.include_router(workflow_router)
    
    # Mock workflow components
    mock_router = Mock(spec=WorkflowAwareRouter)
    mock_router.workflow_manager = Mock(spec=WorkflowContextManager)
    mock_router.get_workflow_stats = AsyncMock(return_value={
        "workflow_routing": {
            "total_requests": 100,
            "cache_hits": 75,
            "cache_hit_rate": 0.75
        },
        "workflow_manager": {
            "active_workflows": 5,
            "total_agents": 15
        }
    })
    
    mock_message_queue = Mock(spec=WorkflowMessageQueue)
    mock_message_queue.send_message = AsyncMock(return_value=True)
    mock_message_queue.receive_messages = AsyncMock(return_value=[])
    mock_message_queue.get_queue_stats = AsyncMock(return_value={
        "total_queues": 5,
        "total_messages_sent": 50,
        "total_messages_received": 45
    })
    
    app.state.router = mock_router
    app.state.message_queue = mock_message_queue
    
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


class TestWorkflowAPI:
    """Test workflow API endpoints."""
    
    def test_send_message(self, client):
        """Test sending agent message."""
        workflow_id = "test-workflow-123"
        
        response = client.post(
            f"/v1/workflows/{workflow_id}/messages",
            json={
                "source_agent": "agent-1",
                "target_agent": "agent-2",
                "message_type": "data",
                "payload": {"findings": ["trend_up", "anomaly_q4"]},
                "ttl": 300
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "sent"
        assert "message_id" in data
        assert "timestamp" in data
    
    def test_send_message_without_queue(self, app, client):
        """Test sending message when queue not available."""
        # Remove message queue
        delattr(app.state, 'message_queue')
        
        workflow_id = "test-workflow-123"
        
        response = client.post(
            f"/v1/workflows/{workflow_id}/messages",
            json={
                "source_agent": "agent-1",
                "target_agent": "agent-2",
                "payload": {"data": "test"}
            }
        )
        
        assert response.status_code == 503
        assert "Message queue service not available" in response.json()["detail"]
    
    def test_get_messages(self, client):
        """Test retrieving agent messages."""
        workflow_id = "test-workflow-123"
        agent_id = "agent-2"
        
        # Mock messages
        from vllm_router.models.workflow import AgentMessage
        import time
        
        mock_messages = [
            AgentMessage(
                workflow_id=workflow_id,
                source_agent="agent-1",
                target_agent=agent_id,
                payload={"data": "test message 1"},
                timestamp=time.time()
            ),
            AgentMessage(
                workflow_id=workflow_id,
                source_agent="agent-3",
                target_agent=agent_id,
                payload={"data": "test message 2"},
                timestamp=time.time()
            )
        ]
        
        # Update mock to return messages
        client.app.state.message_queue.receive_messages = AsyncMock(
            return_value=mock_messages
        )
        
        response = client.get(
            f"/v1/workflows/{workflow_id}/agents/{agent_id}/messages",
            params={"timeout": 1.0, "max_messages": 10}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        assert len(data["messages"]) == 2
        assert data["messages"][0]["source"] == "agent-1"
        assert data["messages"][1]["source"] == "agent-3"
    
    def test_get_workflow_status(self, client):
        """Test getting workflow status."""
        workflow_id = "test-workflow-123"
        
        # Mock workflow context
        from vllm_router.models.workflow import WorkflowContext
        import time
        
        mock_context = WorkflowContext(
            workflow_id=workflow_id,
            created_at=time.time() - 3600,
            total_requests=50,
            cache_hits=35,
            assigned_instance="http://vllm-1:8000"
        )
        mock_context.active_agents = {
            "agent-1": time.time(),
            "agent-2": time.time() - 300,
            "agent-3": time.time() - 600
        }
        
        client.app.state.router.workflow_manager.get_workflow = AsyncMock(
            return_value=mock_context
        )
        
        response = client.get(f"/v1/workflows/{workflow_id}/status")
        
        assert response.status_code == 200
        data = response.json()
        assert data["workflow_id"] == workflow_id
        assert data["active_agents"] == 3
        assert data["total_requests"] == 50
        assert data["cache_hits"] == 35
        assert data["cache_hit_rate"] == 0.7
        assert data["assigned_instance"] == "http://vllm-1:8000"
    
    def test_get_workflow_status_not_found(self, client):
        """Test getting status for non-existent workflow."""
        workflow_id = "non-existent-workflow"
        
        client.app.state.router.workflow_manager.get_workflow = AsyncMock(
            return_value=None
        )
        
        response = client.get(f"/v1/workflows/{workflow_id}/status")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]
    
    def test_get_workflow_status_no_router(self, app, client):
        """Test getting status when router not available."""
        # Remove router
        delattr(app.state, 'router')
        
        workflow_id = "test-workflow-123"
        
        response = client.get(f"/v1/workflows/{workflow_id}/status")
        
        assert response.status_code == 503
        assert "Router not available" in response.json()["detail"]
    
    def test_get_workflow_status_no_workflow_support(self, app, client):
        """Test getting status when router doesn't support workflows."""
        # Mock router without workflow manager
        app.state.router = Mock()
        # Don't add workflow_manager attribute
        
        workflow_id = "test-workflow-123"
        
        response = client.get(f"/v1/workflows/{workflow_id}/status")
        
        assert response.status_code == 501
        assert "Workflow management not supported" in response.json()["detail"]
    
    def test_get_stats(self, client):
        """Test getting overall workflow statistics."""
        response = client.get("/v1/workflows/stats")
        
        assert response.status_code == 200
        data = response.json()
        
        # Check router stats
        assert "workflow_routing" in data
        assert data["workflow_routing"]["total_requests"] == 100
        assert data["workflow_routing"]["cache_hit_rate"] == 0.75
        
        # Check workflow manager stats
        assert "workflow_manager" in data
        assert data["workflow_manager"]["active_workflows"] == 5
        
        # Check message queue stats
        assert "message_queue" in data
        assert data["message_queue"]["total_messages_sent"] == 50


class TestWorkflowValidation:
    """Test workflow API input validation."""
    
    def test_send_message_validation(self, client):
        """Test message validation."""
        workflow_id = "test-workflow"
        
        # Missing required fields
        response = client.post(
            f"/v1/workflows/{workflow_id}/messages",
            json={
                "source_agent": "agent-1"
                # Missing target_agent and payload
            }
        )
        
        assert response.status_code == 422  # Validation error
    
    def test_get_messages_parameters(self, client):
        """Test message retrieval parameters."""
        workflow_id = "test-workflow"
        agent_id = "agent-1"
        
        # Test with custom parameters
        response = client.get(
            f"/v1/workflows/{workflow_id}/agents/{agent_id}/messages",
            params={
                "timeout": 2.5,
                "max_messages": 50
            }
        )
        
        assert response.status_code == 200
        
        # Verify the parameters were passed to the mock
        client.app.state.message_queue.receive_messages.assert_called_with(
            workflow_id=workflow_id,
            agent_id=agent_id,
            timeout=2.5,
            max_messages=50
        )


class TestWorkflowIntegration:
    """Integration tests for complete workflow scenarios."""
    
    def test_multi_agent_workflow(self, client):
        """Test complete multi-agent workflow scenario."""
        workflow_id = "analysis-workflow-001"
        
        # Step 1: Agent 1 sends data to Agent 2
        response1 = client.post(
            f"/v1/workflows/{workflow_id}/messages",
            json={
                "source_agent": "data-collector",
                "target_agent": "analyzer",
                "payload": {"raw_data": [1, 2, 3, 4, 5]},
                "message_type": "data"
            }
        )
        assert response1.status_code == 200
        
        # Step 2: Agent 2 sends results to Agent 3
        response2 = client.post(
            f"/v1/workflows/{workflow_id}/messages",
            json={
                "source_agent": "analyzer",
                "target_agent": "reporter",
                "payload": {"analysis": "trend_up", "confidence": 0.85},
                "message_type": "data"
            }
        )
        assert response2.status_code == 200
        
        # Step 3: Check workflow status
        from vllm_router.models.workflow import WorkflowContext
        import time
        
        mock_context = WorkflowContext(
            workflow_id=workflow_id,
            total_requests=6,  # 3 agents, 2 requests each
            cache_hits=4,
            assigned_instance="http://vllm-1:8000"
        )
        mock_context.active_agents = {
            "data-collector": time.time(),
            "analyzer": time.time(),
            "reporter": time.time()
        }
        
        client.app.state.router.workflow_manager.get_workflow = AsyncMock(
            return_value=mock_context
        )
        
        status_response = client.get(f"/v1/workflows/{workflow_id}/status")
        assert status_response.status_code == 200
        
        status_data = status_response.json()
        assert status_data["active_agents"] == 3
        assert status_data["cache_hit_rate"] == pytest.approx(0.67, rel=0.1)