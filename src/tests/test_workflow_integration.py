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

"""Comprehensive integration tests for workflow-aware routing system."""

import pytest
import asyncio
import time
import uuid
from unittest.mock import Mock, AsyncMock, MagicMock
from typing import Dict, List, Any

from vllm_router.models.workflow import WorkflowMetadata, WorkflowContext, AgentMessage
from vllm_router.services.workflow_service import WorkflowContextManager, WorkflowMessageQueue
from vllm_router.routers.workflow_aware_router import WorkflowAwareRouter
from vllm_router.service_discovery import EndpointInfo


class TestWorkflowIntegrationScenarios:
    """Test complete workflow scenarios end-to-end."""
    
    @pytest.mark.asyncio
    async def test_complete_financial_analysis_workflow(self):
        """Test a complete financial analysis workflow with multiple agents."""
        # Setup
        workflow_manager = WorkflowContextManager(ttl=3600, max_workflows=100)
        message_queue = WorkflowMessageQueue(max_queue_size=1000)
        
        await workflow_manager.start()
        await message_queue.start()
        
        try:
            workflow_id = f"financial-analysis-{uuid.uuid4().hex[:8]}"
            
            # Step 1: Data Analyst Agent
            metadata_analyst = WorkflowMetadata(
                workflow_id=workflow_id,
                agent_id="data-analyst",
                workflow_priority=1.0,
                context_sharing_strategy="auto"
            )
            
            context = await workflow_manager.register_workflow(workflow_id, metadata_analyst)
            assert context is not None
            assert context.workflow_id == workflow_id
            
            # Simulate processing
            context.update_stats(cache_hit=False, tokens=150)
            
            # Step 2: Risk Assessor Agent (shares context)
            metadata_risk = WorkflowMetadata(
                workflow_id=workflow_id,
                agent_id="risk-assessor",
                parent_request_id="analyst-request-001"
            )
            
            # Should get same context (workflow affinity)
            existing_context = await workflow_manager.get_workflow(workflow_id)
            assert existing_context is not None
            assert existing_context.workflow_id == workflow_id
            
            # Simulate cache hit due to shared context
            existing_context.update_stats(cache_hit=True, tokens=120)
            
            # Step 3: Agent-to-Agent Communication
            findings_message = AgentMessage(
                workflow_id=workflow_id,
                source_agent="data-analyst",
                target_agent="risk-assessor",
                payload={
                    "findings": ["revenue_growth", "margin_improvement"],
                    "confidence": 0.85,
                    "recommendations": ["expand_marketing", "optimize_costs"]
                },
                message_type="analysis_results"
            )
            
            success = await message_queue.send_message(findings_message)
            assert success is True
            
            # Risk assessor receives message
            messages = await message_queue.receive_messages(
                workflow_id=workflow_id,
                agent_id="risk-assessor",
                timeout=1.0
            )
            
            assert len(messages) == 1
            assert messages[0].source_agent == "data-analyst"
            assert messages[0].payload["confidence"] == 0.85
            
            # Step 4: Strategic Advisor Agent
            metadata_strategy = WorkflowMetadata(
                workflow_id=workflow_id,
                agent_id="strategic-advisor"
            )
            
            # Should benefit from accumulated cache
            existing_context.update_stats(cache_hit=True, tokens=180)
            
            # Step 5: Final workflow statistics
            stats = existing_context.get_cache_hit_rate()
            assert stats == 2.0/3.0  # 2 cache hits out of 3 requests
            
            assert existing_context.total_requests == 3
            assert existing_context.cache_hits == 2
            assert existing_context.total_tokens == 450
            
        finally:
            await workflow_manager.stop()
            await message_queue.stop()
    
    @pytest.mark.asyncio
    async def test_parallel_research_collaboration(self):
        """Test parallel agents collaborating on research task."""
        workflow_manager = WorkflowContextManager()
        message_queue = WorkflowMessageQueue()
        
        await workflow_manager.start()
        await message_queue.start()
        
        try:
            workflow_id = f"research-collab-{uuid.uuid4().hex[:8]}"
            
            # Create multiple parallel agents
            agents = ["literature-researcher", "technical-analyst", "market-researcher"]
            contexts = []
            
            # Register all agents in parallel
            for agent_id in agents:
                metadata = WorkflowMetadata(
                    workflow_id=workflow_id,
                    agent_id=agent_id,
                    context_sharing_strategy="broadcast"
                )
                context = await workflow_manager.register_workflow(workflow_id, metadata)
                contexts.append(context)
            
            # All should share the same workflow context
            assert all(ctx.workflow_id == workflow_id for ctx in contexts)
            
            # Simulate parallel processing with message exchanges
            tasks = []
            
            # Literature researcher shares findings
            tasks.append(message_queue.send_message(AgentMessage(
                workflow_id=workflow_id,
                source_agent="literature-researcher",
                target_agent="technical-analyst",
                payload={"research_papers": ["paper1", "paper2"], "key_insights": ["insight1", "insight2"]}
            )))
            
            # Market researcher shares data
            tasks.append(message_queue.send_message(AgentMessage(
                workflow_id=workflow_id,
                source_agent="market-researcher", 
                target_agent="technical-analyst",
                payload={"market_trends": ["trend1", "trend2"], "opportunities": ["opp1", "opp2"]}
            )))
            
            # Technical analyst broadcasts synthesis
            tasks.append(message_queue.send_message(AgentMessage(
                workflow_id=workflow_id,
                source_agent="technical-analyst",
                target_agent="literature-researcher",
                payload={"synthesis": "combined_analysis", "next_steps": ["step1", "step2"]}
            )))
            
            results = await asyncio.gather(*tasks)
            assert all(result is True for result in results)
            
            # Verify message delivery
            lit_messages = await message_queue.receive_messages(workflow_id, "literature-researcher", timeout=1.0)
            tech_messages = await message_queue.receive_messages(workflow_id, "technical-analyst", timeout=1.0)
            
            assert len(lit_messages) == 1  # Received synthesis from technical analyst
            assert len(tech_messages) == 2  # Received from both other agents
            
        finally:
            await workflow_manager.stop()
            await message_queue.stop()
    
    @pytest.mark.asyncio
    async def test_workflow_router_integration(self):
        """Test workflow-aware router with real routing decisions."""
        # Create router with test configuration
        router = WorkflowAwareRouter(
            lmcache_controller_port=9000,
            session_key="test-session",
            workflow_ttl=3600,
            max_workflows=100,
            batching_preference=0.8,
            gpu_weight=0.4,
            memory_weight=0.3,
            qps_weight=0.3
        )
        
        # Mock the KV manager start
        router.start_kv_manager = Mock()
        
        await router.start()
        
        try:
            # Create test endpoints
            endpoints = [
                EndpointInfo(url="http://vllm-1:8000", model_names=["llama"]),
                EndpointInfo(url="http://vllm-2:8000", model_names=["llama"]),
                EndpointInfo(url="http://vllm-3:8000", model_names=["llama"])
            ]
            
            # Mock request and stats
            request = Mock()
            request.headers = {}
            
            engine_stats = {}
            request_stats = {}
            
            workflow_id = f"router-test-{uuid.uuid4().hex[:8]}"
            
            # Test workflow-aware routing
            request_json_1 = {
                "model": "llama",
                "prompt": "First request in workflow",
                "workflow_metadata": {
                    "workflow_id": workflow_id,
                    "agent_id": "agent-1"
                }
            }
            
            url_1 = await router.route_request(endpoints, engine_stats, request_stats, request, request_json_1)
            assert url_1 in [ep.url for ep in endpoints]
            
            # Second request should route to same instance
            request_json_2 = {
                "model": "llama", 
                "prompt": "Second request in workflow",
                "workflow_metadata": {
                    "workflow_id": workflow_id,
                    "agent_id": "agent-2"
                }
            }
            
            url_2 = await router.route_request(endpoints, engine_stats, request_stats, request, request_json_2)
            assert url_2 == url_1  # Should route to same instance
            
            # Verify workflow statistics
            assert router.total_workflow_requests == 2
            
            # Test non-workflow request (should use parent routing)
            request_json_3 = {
                "model": "llama",
                "prompt": "Non-workflow request"
                # No workflow_metadata
            }
            
            # Mock parent routing behavior
            original_route = router.__class__.__bases__[0].route_request
            router.__class__.__bases__[0].route_request = AsyncMock(return_value="http://vllm-1:8000")
            
            url_3 = await router.route_request(endpoints, engine_stats, request_stats, request, request_json_3)
            assert url_3 == "http://vllm-1:8000"
            
            # Workflow requests count should remain the same
            assert router.total_workflow_requests == 2
            
        finally:
            await router.stop()
    
    @pytest.mark.asyncio 
    async def test_workflow_lifecycle_management(self):
        """Test complete workflow lifecycle including cleanup."""
        workflow_manager = WorkflowContextManager(ttl=2, cleanup_interval=1)  # Short TTL for testing
        
        await workflow_manager.start()
        
        try:
            workflow_id = f"lifecycle-test-{uuid.uuid4().hex[:8]}"
            
            # Create workflow
            metadata = WorkflowMetadata(workflow_id=workflow_id, agent_id="test-agent")
            context = await workflow_manager.register_workflow(workflow_id, metadata)
            
            assert context is not None
            assert await workflow_manager.get_workflow(workflow_id) is not None
            
            # Workflow should be active
            assert context.is_active(ttl=2)
            
            # Wait for TTL to expire
            await asyncio.sleep(3)
            
            # Workflow should be cleaned up
            assert await workflow_manager.get_workflow(workflow_id) is None
            assert workflow_manager.total_workflows_expired >= 1
            
        finally:
            await workflow_manager.stop()
    
    @pytest.mark.asyncio
    async def test_message_queue_overflow_handling(self):
        """Test message queue behavior under high load."""
        message_queue = WorkflowMessageQueue(max_queue_size=3)  # Small queue for testing
        
        await message_queue.start()
        
        try:
            workflow_id = f"overflow-test-{uuid.uuid4().hex[:8]}"
            
            # Fill queue to capacity
            messages_sent = 0
            for i in range(5):  # Try to send more than capacity
                message = AgentMessage(
                    workflow_id=workflow_id,
                    source_agent="sender",
                    target_agent="receiver",
                    payload={"data": f"message-{i}"}
                )
                
                success = await message_queue.send_message(message)
                if success:
                    messages_sent += 1
            
            # Should have sent only up to queue capacity
            assert messages_sent <= 3
            
            # Verify messages can be received
            received_messages = await message_queue.receive_messages(
                workflow_id=workflow_id,
                agent_id="receiver",
                timeout=1.0
            )
            
            assert len(received_messages) == messages_sent
            
        finally:
            await message_queue.stop()


class TestWorkflowErrorHandling:
    """Test error handling and edge cases."""
    
    @pytest.mark.asyncio
    async def test_invalid_workflow_operations(self):
        """Test handling of invalid workflow operations."""
        workflow_manager = WorkflowContextManager()
        message_queue = WorkflowMessageQueue()
        
        await workflow_manager.start()
        await message_queue.start()
        
        try:
            # Test getting non-existent workflow
            result = await workflow_manager.get_workflow("non-existent-workflow")
            assert result is None
            
            # Test sending message to non-existent workflow
            invalid_message = AgentMessage(
                workflow_id="non-existent-workflow",
                source_agent="sender",
                target_agent="receiver", 
                payload={"data": "test"}
            )
            
            success = await message_queue.send_message(invalid_message)
            # Should still succeed (queue creates workflow queues on demand)
            assert success is True
            
            # Test receiving from non-existent workflow
            messages = await message_queue.receive_messages(
                workflow_id="non-existent-workflow",
                agent_id="receiver",
                timeout=0.1
            )
            
            assert len(messages) == 1  # Should get the message we just sent
            
        finally:
            await workflow_manager.stop()
            await message_queue.stop()
    
    @pytest.mark.asyncio
    async def test_concurrent_workflow_access(self):
        """Test concurrent access to workflow resources."""
        workflow_manager = WorkflowContextManager()
        
        await workflow_manager.start()
        
        try:
            workflow_id = f"concurrent-test-{uuid.uuid4().hex[:8]}"
            
            # Create multiple concurrent registrations
            async def register_agent(agent_id: str):
                metadata = WorkflowMetadata(
                    workflow_id=workflow_id,
                    agent_id=agent_id
                )
                return await workflow_manager.register_workflow(workflow_id, metadata)
            
            # Run concurrent registrations
            tasks = [register_agent(f"agent-{i}") for i in range(10)]
            contexts = await asyncio.gather(*tasks)
            
            # All should succeed and reference the same workflow
            assert all(ctx is not None for ctx in contexts)
            assert all(ctx.workflow_id == workflow_id for ctx in contexts)
            
            # Verify only one workflow context was created
            unique_contexts = len(set(id(ctx) for ctx in contexts))
            assert unique_contexts == 1  # All should reference the same object
            
        finally:
            await workflow_manager.stop()


class TestWorkflowPerformanceRegression:
    """Performance regression tests to ensure optimizations work."""
    
    @pytest.mark.asyncio
    async def test_workflow_assignment_performance(self):
        """Test that workflow assignment is fast even with many workflows."""
        workflow_manager = WorkflowContextManager(max_workflows=1000)
        
        await workflow_manager.start()
        
        try:
            # Create many workflows
            workflow_ids = [f"perf-test-{i}" for i in range(100)]
            
            start_time = time.time()
            
            for workflow_id in workflow_ids:
                metadata = WorkflowMetadata(workflow_id=workflow_id, agent_id="test-agent")
                await workflow_manager.register_workflow(workflow_id, metadata)
            
            registration_time = time.time() - start_time
            
            # Should complete quickly (< 1 second for 100 workflows)
            assert registration_time < 1.0
            
            # Test lookup performance
            start_time = time.time()
            
            for workflow_id in workflow_ids:
                context = await workflow_manager.get_workflow(workflow_id)
                assert context is not None
            
            lookup_time = time.time() - start_time
            
            # Lookups should be very fast (< 0.1 seconds for 100 lookups)
            assert lookup_time < 0.1
            
        finally:
            await workflow_manager.stop()
    
    @pytest.mark.asyncio
    async def test_message_queue_throughput(self):
        """Test message queue can handle high throughput."""
        message_queue = WorkflowMessageQueue(max_queue_size=10000)
        
        await message_queue.start()
        
        try:
            workflow_id = f"throughput-test-{uuid.uuid4().hex[:8]}"
            num_messages = 1000
            
            # Send many messages quickly
            start_time = time.time()
            
            tasks = []
            for i in range(num_messages):
                message = AgentMessage(
                    workflow_id=workflow_id,
                    source_agent="sender",
                    target_agent="receiver",
                    payload={"data": f"message-{i}"}
                )
                tasks.append(message_queue.send_message(message))
            
            results = await asyncio.gather(*tasks)
            send_time = time.time() - start_time
            
            # All messages should be sent successfully
            assert all(results)
            
            # Should achieve good throughput (> 100 msgs/sec)
            throughput = num_messages / send_time
            assert throughput > 100
            
            # Receive all messages
            start_time = time.time()
            
            received_messages = await message_queue.receive_messages(
                workflow_id=workflow_id,
                agent_id="receiver",
                timeout=5.0,
                max_messages=num_messages
            )
            
            receive_time = time.time() - start_time
            
            assert len(received_messages) == num_messages
            
            # Receive throughput should also be good
            receive_throughput = num_messages / receive_time
            assert receive_throughput > 100
            
        finally:
            await message_queue.stop()