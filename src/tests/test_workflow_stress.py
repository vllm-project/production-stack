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

"""Stress tests for workflow-aware routing system under extreme load."""

import pytest
import asyncio
import time
import uuid
import random
from typing import List, Dict, Any
from unittest.mock import Mock

from vllm_router.models.workflow import WorkflowMetadata, AgentMessage
from vllm_router.services.workflow_service import WorkflowContextManager, WorkflowMessageQueue
from vllm_router.routers.workflow_aware_router import WorkflowAwareRouter


class TestExtremeConcurrencyStress:
    """Test system behavior under extreme concurrent load."""
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_thousand_concurrent_workflows(self):
        """Test 1000 concurrent workflows with multiple agents each."""
        num_workflows = 1000
        agents_per_workflow = 3
        
        workflow_manager = WorkflowContextManager(max_workflows=num_workflows * 2)
        message_queue = WorkflowMessageQueue(max_queue_size=num_workflows * agents_per_workflow * 10)
        
        await workflow_manager.start()
        await message_queue.start()
        
        try:
            async def create_workflow_with_agents(workflow_index: int):
                """Create a workflow with multiple agents and inter-agent communication."""
                workflow_id = f"stress-1k-{workflow_index}"
                
                # Create agents for this workflow
                agents = []
                for agent_index in range(agents_per_workflow):
                    agent_id = f"agent-{agent_index}"
                    metadata = WorkflowMetadata(
                        workflow_id=workflow_id,
                        agent_id=agent_id,
                        workflow_priority=random.uniform(0.5, 2.0)
                    )
                    context = await workflow_manager.register_workflow(workflow_id, metadata)
                    if context:
                        agents.append(agent_id)
                
                # Send messages between agents
                messages_sent = 0
                for i in range(len(agents) - 1):
                    message = AgentMessage(
                        workflow_id=workflow_id,
                        source_agent=agents[i],
                        target_agent=agents[i + 1],
                        payload={"workflow_index": workflow_index, "step": i}
                    )
                    success = await message_queue.send_message(message)
                    if success:
                        messages_sent += 1
                
                return len(agents), messages_sent
            
            print(f"Starting stress test with {num_workflows} concurrent workflows...")
            start_time = time.time()
            
            # Create all workflows concurrently
            tasks = [create_workflow_with_agents(i) for i in range(num_workflows)]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            total_time = time.time() - start_time
            
            # Analyze results
            successful_workflows = [r for r in results if not isinstance(r, Exception)]
            failed_workflows = [r for r in results if isinstance(r, Exception)]
            
            total_agents = sum(r[0] for r in successful_workflows)
            total_messages = sum(r[1] for r in successful_workflows)
            
            print(f"Stress test completed in {total_time:.2f}s:")
            print(f"  Successful workflows: {len(successful_workflows)}/{num_workflows}")
            print(f"  Total agents created: {total_agents}")
            print(f"  Total messages sent: {total_messages}")
            print(f"  Failed workflows: {len(failed_workflows)}")
            
            # Performance assertions
            success_rate = len(successful_workflows) / num_workflows
            assert success_rate > 0.95, f"Success rate {success_rate:.2%} below 95% threshold"
            assert total_time < 30.0, f"Total time {total_time:.2f}s exceeds 30s threshold"
            
            # System should remain responsive
            assert workflow_manager.total_workflows_created >= len(successful_workflows)
            
        finally:
            await workflow_manager.stop()
            await message_queue.stop()
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_message_flood_handling(self):
        """Test handling of message flood scenarios."""
        message_queue = WorkflowMessageQueue(max_queue_size=50000)
        await message_queue.start()
        
        try:
            num_workflows = 10
            messages_per_workflow = 1000
            total_messages = num_workflows * messages_per_workflow
            
            async def flood_workflow(workflow_index: int):
                """Flood a single workflow with messages."""
                workflow_id = f"flood-{workflow_index}"
                successful_sends = 0
                
                for msg_index in range(messages_per_workflow):
                    message = AgentMessage(
                        workflow_id=workflow_id,
                        source_agent="flooder",
                        target_agent="receiver",
                        payload={
                            "flood_index": workflow_index,
                            "message_index": msg_index,
                            "data": f"flood-data-{msg_index}"
                        }
                    )
                    
                    success = await message_queue.send_message(message)
                    if success:
                        successful_sends += 1
                
                return successful_sends
            
            print(f"Starting message flood test: {total_messages} messages across {num_workflows} workflows...")
            start_time = time.time()
            
            # Flood all workflows concurrently
            flood_tasks = [flood_workflow(i) for i in range(num_workflows)]
            send_results = await asyncio.gather(*flood_tasks)
            
            send_time = time.time() - start_time
            total_sent = sum(send_results)
            
            print(f"Message flood completed in {send_time:.2f}s:")
            print(f"  Messages sent: {total_sent}/{total_messages}")
            print(f"  Send rate: {total_sent/send_time:.1f} msgs/sec")
            
            # Test message retrieval under load
            receive_start = time.time()
            total_received = 0
            
            for workflow_index in range(num_workflows):
                workflow_id = f"flood-{workflow_index}"
                messages = await message_queue.receive_messages(
                    workflow_id=workflow_id,
                    agent_id="receiver",
                    timeout=5.0,
                    max_messages=messages_per_workflow
                )
                total_received += len(messages)
            
            receive_time = time.time() - receive_start
            
            print(f"  Messages received: {total_received}")
            print(f"  Receive rate: {total_received/receive_time:.1f} msgs/sec")
            
            # Performance assertions
            assert total_sent > total_messages * 0.9, f"Only {total_sent}/{total_messages} messages sent successfully"
            assert total_received == total_sent, f"Message loss: sent {total_sent}, received {total_received}"
            assert send_time < 10.0, f"Send time {send_time:.2f}s exceeds 10s threshold"
            assert receive_time < 10.0, f"Receive time {receive_time:.2f}s exceeds 10s threshold"
            
        finally:
            await message_queue.stop()
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_rapid_workflow_churn(self):
        """Test rapid creation and destruction of workflows."""
        workflow_manager = WorkflowContextManager(ttl=2, cleanup_interval=0.5, max_workflows=500)
        await workflow_manager.start()
        
        try:
            churn_duration = 10.0  # Run for 10 seconds
            workflows_created = 0
            workflows_active = 0
            
            async def workflow_churner():
                """Continuously create workflows that will expire."""
                nonlocal workflows_created
                
                while True:
                    workflow_id = f"churn-{workflows_created}-{uuid.uuid4().hex[:8]}"
                    metadata = WorkflowMetadata(
                        workflow_id=workflow_id,
                        agent_id=f"churner-{workflows_created % 100}"
                    )
                    
                    context = await workflow_manager.register_workflow(workflow_id, metadata)
                    if context:
                        workflows_created += 1
                    
                    # Small delay to prevent overwhelming the system
                    await asyncio.sleep(0.01)
            
            async def active_counter():
                """Count active workflows periodically."""
                nonlocal workflows_active
                
                while True:
                    # Count active workflows (simplified - would need access to internal state)
                    workflows_active = workflow_manager.total_workflows_created - workflow_manager.total_workflows_expired
                    await asyncio.sleep(0.1)
            
            print(f"Starting workflow churn test for {churn_duration}s...")
            
            # Start churning and counting
            churn_task = asyncio.create_task(workflow_churner())
            count_task = asyncio.create_task(active_counter())
            
            # Run for specified duration
            await asyncio.sleep(churn_duration)
            
            # Stop churning
            churn_task.cancel()
            count_task.cancel()
            
            # Wait a bit for cleanup
            await asyncio.sleep(3.0)
            
            final_active = workflow_manager.total_workflows_created - workflow_manager.total_workflows_expired
            churn_rate = workflows_created / churn_duration
            
            print(f"Churn test completed:")
            print(f"  Workflows created: {workflows_created}")
            print(f"  Creation rate: {churn_rate:.1f} workflows/sec")
            print(f"  Final active workflows: {final_active}")
            print(f"  Workflows expired: {workflow_manager.total_workflows_expired}")
            
            # Performance assertions
            assert churn_rate > 10.0, f"Churn rate {churn_rate:.1f} workflows/sec below 10/sec threshold"
            assert final_active < 50, f"Too many active workflows remaining: {final_active}"
            assert workflow_manager.total_workflows_expired > 0, "No workflows were expired during test"
            
        finally:
            await workflow_manager.stop()


class TestResourceExhaustionHandling:
    """Test system behavior when resources are exhausted."""
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_workflow_limit_enforcement(self):
        """Test behavior when workflow limit is reached."""
        max_workflows = 20  # Small limit for testing
        workflow_manager = WorkflowContextManager(max_workflows=max_workflows)
        
        await workflow_manager.start()
        
        try:
            # Fill up to the limit
            workflow_ids = []
            for i in range(max_workflows):
                workflow_id = f"limit-test-{i}"
                metadata = WorkflowMetadata(workflow_id=workflow_id, agent_id=f"agent-{i}")
                context = await workflow_manager.register_workflow(workflow_id, metadata)
                assert context is not None, f"Failed to create workflow {i} within limit"
                workflow_ids.append(workflow_id)
            
            # Try to create beyond the limit
            overflow_attempts = 10
            overflow_successes = 0
            
            for i in range(overflow_attempts):
                overflow_id = f"overflow-{i}"
                metadata = WorkflowMetadata(workflow_id=overflow_id, agent_id=f"overflow-{i}")
                context = await workflow_manager.register_workflow(overflow_id, metadata)
                
                if context is not None:
                    overflow_successes += 1
            
            print(f"Limit enforcement test:")
            print(f"  Max workflows: {max_workflows}")
            print(f"  Workflows created within limit: {len(workflow_ids)}")
            print(f"  Overflow attempts: {overflow_attempts}")
            print(f"  Overflow successes: {overflow_successes}")
            
            # System should handle overflow gracefully
            total_created = workflow_manager.total_workflows_created
            assert total_created >= max_workflows, "Should have created at least the limit"
            
            # System should still be responsive
            existing_workflow = await workflow_manager.get_workflow(workflow_ids[0])
            assert existing_workflow is not None, "Existing workflows should still be accessible"
            
        finally:
            await workflow_manager.stop()
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_memory_pressure_simulation(self):
        """Simulate memory pressure with large payloads."""
        message_queue = WorkflowMessageQueue(max_queue_size=1000, max_message_size=1024*1024)  # 1MB max
        await message_queue.start()
        
        try:
            workflow_id = f"memory-pressure-{uuid.uuid4().hex[:8]}"
            
            # Create messages with varying payload sizes
            payload_sizes = [1024, 10*1024, 100*1024, 500*1024]  # 1KB to 500KB
            messages_per_size = 10
            
            total_sent = 0
            total_payload_size = 0
            
            for size in payload_sizes:
                large_payload = {"data": "x" * size, "size": size}
                
                for i in range(messages_per_size):
                    message = AgentMessage(
                        workflow_id=workflow_id,
                        source_agent="memory-tester",
                        target_agent="memory-receiver",
                        payload=large_payload
                    )
                    
                    success = await message_queue.send_message(message)
                    if success:
                        total_sent += 1
                        total_payload_size += size
            
            print(f"Memory pressure test:")
            print(f"  Messages sent: {total_sent}")
            print(f"  Total payload size: {total_payload_size/1024/1024:.1f} MB")
            
            # Retrieve messages
            start_time = time.time()
            messages = await message_queue.receive_messages(
                workflow_id=workflow_id,
                agent_id="memory-receiver",
                timeout=5.0,
                max_messages=total_sent
            )
            retrieve_time = time.time() - start_time
            
            print(f"  Messages retrieved: {len(messages)}")
            print(f"  Retrieval time: {retrieve_time:.2f}s")
            
            # Verify data integrity
            assert len(messages) == total_sent, f"Message loss: sent {total_sent}, received {len(messages)}"
            assert retrieve_time < 5.0, f"Retrieval too slow: {retrieve_time:.2f}s"
            
            # Verify payload integrity
            for msg in messages:
                expected_size = msg.payload["size"]
                actual_size = len(msg.payload["data"])
                assert actual_size == expected_size, f"Payload corruption: expected {expected_size}, got {actual_size}"
            
        finally:
            await message_queue.stop()


class TestFailureRecoveryStress:
    """Test system resilience under failure conditions."""
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_routing_under_endpoint_failures(self):
        """Test routing behavior when endpoints fail."""
        router = WorkflowAwareRouter(
            lmcache_controller_port=9000,
            session_key="failure-test",
            workflow_ttl=3600
        )
        
        router.start_kv_manager = Mock()
        await router.start()
        
        try:
            from vllm_router.service_discovery import EndpointInfo
            
            # Start with healthy endpoints
            all_endpoints = [
                EndpointInfo(url=f"http://vllm-{i}:8000", model_names=["llama"])
                for i in range(1, 6)
            ]
            
            # Simulate progressive endpoint failures
            failure_scenarios = [
                all_endpoints,  # All healthy
                all_endpoints[1:],  # First endpoint fails
                all_endpoints[2:],  # Two endpoints fail
                all_endpoints[3:],  # Three endpoints fail
                all_endpoints[4:],  # Only one endpoint remains
            ]
            
            request = Mock()
            request.headers = {}
            engine_stats = {}
            request_stats = {}
            
            for scenario_index, available_endpoints in enumerate(failure_scenarios):
                print(f"Testing with {len(available_endpoints)} available endpoints...")
                
                # Test multiple workflows with current endpoint set
                for workflow_index in range(10):
                    workflow_id = f"failure-test-{scenario_index}-{workflow_index}"
                    
                    request_json = {
                        "model": "llama",
                        "prompt": f"Test request for scenario {scenario_index}",
                        "workflow_metadata": {
                            "workflow_id": workflow_id,
                            "agent_id": f"agent-{workflow_index}"
                        }
                    }
                    
                    try:
                        url = await router.route_request(
                            available_endpoints, engine_stats, request_stats, request, request_json
                        )
                        assert url in [ep.url for ep in available_endpoints]
                        
                        # Subsequent requests should maintain affinity
                        for agent_index in range(3):
                            request_json["workflow_metadata"]["agent_id"] = f"agent-{workflow_index}-{agent_index}"
                            
                            affinity_url = await router.route_request(
                                available_endpoints, engine_stats, request_stats, request, request_json
                            )
                            
                            # Should route to same endpoint if it's still available
                            if url in [ep.url for ep in available_endpoints]:
                                assert affinity_url == url, f"Lost affinity: {url} -> {affinity_url}"
                    
                    except Exception as e:
                        # Should handle failures gracefully
                        if len(available_endpoints) == 0:
                            print(f"Expected failure with no endpoints: {e}")
                        else:
                            pytest.fail(f"Unexpected routing failure with {len(available_endpoints)} endpoints: {e}")
            
            print("Endpoint failure test completed successfully")
            
        finally:
            await router.stop()
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_message_queue_recovery(self):
        """Test message queue recovery from simulated failures."""
        message_queue = WorkflowMessageQueue(max_queue_size=1000)
        await message_queue.start()
        
        try:
            workflow_id = f"recovery-test-{uuid.uuid4().hex[:8]}"
            
            # Send initial batch of messages
            initial_messages = 50
            for i in range(initial_messages):
                message = AgentMessage(
                    workflow_id=workflow_id,
                    source_agent="recovery-sender",
                    target_agent="recovery-receiver",
                    payload={"phase": "initial", "index": i}
                )
                success = await message_queue.send_message(message)
                assert success
            
            # Simulate partial message consumption (simulating agent failure/restart)
            partial_messages = await message_queue.receive_messages(
                workflow_id=workflow_id,
                agent_id="recovery-receiver",
                timeout=1.0,
                max_messages=20  # Only consume part of the messages
            )
            assert len(partial_messages) == 20
            
            # Send more messages while some are still queued
            additional_messages = 30
            for i in range(additional_messages):
                message = AgentMessage(
                    workflow_id=workflow_id,
                    source_agent="recovery-sender",
                    target_agent="recovery-receiver",
                    payload={"phase": "additional", "index": i}
                )
                success = await message_queue.send_message(message)
                assert success
            
            # Consume remaining messages
            remaining_messages = await message_queue.receive_messages(
                workflow_id=workflow_id,
                agent_id="recovery-receiver",
                timeout=2.0,
                max_messages=1000  # Get all remaining
            )
            
            # Verify message integrity and ordering
            total_received = len(partial_messages) + len(remaining_messages)
            expected_total = initial_messages + additional_messages
            
            assert total_received == expected_total, f"Message loss: expected {expected_total}, got {total_received}"
            
            # Verify phases are preserved
            initial_count = sum(1 for msg in partial_messages + remaining_messages if msg.payload["phase"] == "initial")
            additional_count = sum(1 for msg in partial_messages + remaining_messages if msg.payload["phase"] == "additional")
            
            assert initial_count == initial_messages, f"Initial message loss: expected {initial_messages}, got {initial_count}"
            assert additional_count == additional_messages, f"Additional message loss: expected {additional_messages}, got {additional_count}"
            
            print(f"Message queue recovery test:")
            print(f"  Total messages: {expected_total}")
            print(f"  Received messages: {total_received}")
            print(f"  Initial phase: {initial_count}")
            print(f"  Additional phase: {additional_count}")
            
        finally:
            await message_queue.stop()