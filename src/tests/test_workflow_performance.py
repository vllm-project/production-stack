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

"""Performance regression tests for workflow-aware routing system."""

import pytest
import asyncio
import time
import statistics
import uuid
from typing import List, Dict, Any
from unittest.mock import Mock, AsyncMock

from vllm_router.models.workflow import WorkflowMetadata, WorkflowContext, AgentMessage
from vllm_router.services.workflow_service import WorkflowContextManager, WorkflowMessageQueue
from vllm_router.routers.workflow_aware_router import WorkflowAwareRouter


class TestWorkflowPerformanceBenchmarks:
    """Performance benchmarks to prevent regression."""
    
    @pytest.mark.asyncio
    @pytest.mark.performance
    async def test_workflow_registration_latency(self):
        """Test workflow registration latency stays under threshold."""
        workflow_manager = WorkflowContextManager()
        await workflow_manager.start()
        
        try:
            num_workflows = 50
            latencies = []
            
            for i in range(num_workflows):
                workflow_id = f"perf-reg-{i}"
                metadata = WorkflowMetadata(
                    workflow_id=workflow_id,
                    agent_id=f"agent-{i}"
                )
                
                start_time = time.time()
                context = await workflow_manager.register_workflow(workflow_id, metadata)
                latency = time.time() - start_time
                
                latencies.append(latency)
                assert context is not None
            
            # Performance assertions
            avg_latency = statistics.mean(latencies)
            p95_latency = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies)
            
            # Regression thresholds (these should not increase over time)
            assert avg_latency < 0.01, f"Average registration latency {avg_latency:.4f}s exceeds 10ms threshold"
            assert p95_latency < 0.05, f"P95 registration latency {p95_latency:.4f}s exceeds 50ms threshold"
            assert max(latencies) < 0.1, f"Max registration latency {max(latencies):.4f}s exceeds 100ms threshold"
            
            print(f"Registration performance: avg={avg_latency*1000:.2f}ms, p95={p95_latency*1000:.2f}ms")
            
        finally:
            await workflow_manager.stop()
    
    @pytest.mark.asyncio
    @pytest.mark.performance
    async def test_workflow_lookup_performance(self):
        """Test workflow lookup performance scales with number of workflows."""
        workflow_manager = WorkflowContextManager()
        await workflow_manager.start()
        
        try:
            # Create varying numbers of workflows
            test_sizes = [10, 50, 100, 200]
            results = {}
            
            for size in test_sizes:
                # Setup workflows
                workflow_ids = []
                for i in range(size):
                    workflow_id = f"lookup-test-{size}-{i}"
                    metadata = WorkflowMetadata(workflow_id=workflow_id, agent_id=f"agent-{i}")
                    await workflow_manager.register_workflow(workflow_id, metadata)
                    workflow_ids.append(workflow_id)
                
                # Measure lookup performance
                lookup_times = []
                for workflow_id in workflow_ids:
                    start_time = time.time()
                    context = await workflow_manager.get_workflow(workflow_id)
                    lookup_time = time.time() - start_time
                    lookup_times.append(lookup_time)
                    assert context is not None
                
                avg_lookup_time = statistics.mean(lookup_times)
                results[size] = avg_lookup_time
                
                # Performance should stay under 1ms regardless of size
                assert avg_lookup_time < 0.001, f"Lookup time {avg_lookup_time*1000:.2f}ms exceeds 1ms for {size} workflows"
            
            # Performance should not degrade significantly with scale
            smallest_time = results[test_sizes[0]]
            largest_time = results[test_sizes[-1]]
            degradation_ratio = largest_time / smallest_time
            
            assert degradation_ratio < 3.0, f"Performance degraded {degradation_ratio:.1f}x from {test_sizes[0]} to {test_sizes[-1]} workflows"
            
            print(f"Lookup scaling: {test_sizes[0]}={results[test_sizes[0]]*1000:.3f}ms, {test_sizes[-1]}={results[test_sizes[-1]]*1000:.3f}ms")
            
        finally:
            await workflow_manager.stop()
    
    @pytest.mark.asyncio
    @pytest.mark.performance
    async def test_message_queue_latency(self):
        """Test message queue latency performance."""
        message_queue = WorkflowMessageQueue(max_queue_size=10000)
        await message_queue.start()
        
        try:
            workflow_id = f"msg-latency-{uuid.uuid4().hex[:8]}"
            num_messages = 100
            
            send_latencies = []
            receive_latencies = []
            
            for i in range(num_messages):
                message = AgentMessage(
                    workflow_id=workflow_id,
                    source_agent="sender",
                    target_agent="receiver",
                    payload={"data": f"test-message-{i}"}
                )
                
                # Measure send latency
                start_time = time.time()
                success = await message_queue.send_message(message)
                send_latency = time.time() - start_time
                
                assert success
                send_latencies.append(send_latency)
                
                # Measure receive latency
                start_time = time.time()
                messages = await message_queue.receive_messages(
                    workflow_id=workflow_id,
                    agent_id="receiver",
                    timeout=1.0,
                    max_messages=1
                )
                receive_latency = time.time() - start_time
                
                assert len(messages) == 1
                receive_latencies.append(receive_latency)
            
            # Performance assertions
            avg_send = statistics.mean(send_latencies)
            avg_receive = statistics.mean(receive_latencies)
            p95_send = statistics.quantiles(send_latencies, n=20)[18] if len(send_latencies) >= 20 else max(send_latencies)
            p95_receive = statistics.quantiles(receive_latencies, n=20)[18] if len(receive_latencies) >= 20 else max(receive_latencies)
            
            # Message queue should be very fast (< 5ms average, < 20ms P95)
            assert avg_send < 0.005, f"Average send latency {avg_send*1000:.2f}ms exceeds 5ms threshold"
            assert avg_receive < 0.005, f"Average receive latency {avg_receive*1000:.2f}ms exceeds 5ms threshold"
            assert p95_send < 0.02, f"P95 send latency {p95_send*1000:.2f}ms exceeds 20ms threshold"
            assert p95_receive < 0.02, f"P95 receive latency {p95_receive*1000:.2f}ms exceeds 20ms threshold"
            
            print(f"Message latency: send={avg_send*1000:.2f}ms, receive={avg_receive*1000:.2f}ms")
            
        finally:
            await message_queue.stop()
    
    @pytest.mark.asyncio
    @pytest.mark.performance
    async def test_routing_decision_performance(self):
        """Test workflow-aware routing decision performance."""
        router = WorkflowAwareRouter(
            lmcache_controller_port=9000,
            session_key="perf-test",
            workflow_ttl=3600
        )
        
        # Mock the KV manager
        router.start_kv_manager = Mock()
        await router.start()
        
        try:
            from vllm_router.service_discovery import EndpointInfo
            
            endpoints = [
                EndpointInfo(url=f"http://vllm-{i}:8000", model_names=["llama"])
                for i in range(1, 6)  # 5 endpoints
            ]
            
            request = Mock()
            request.headers = {}
            engine_stats = {}
            request_stats = {}
            
            # Test routing performance with different scenarios
            routing_times = []
            num_requests = 50
            
            for i in range(num_requests):
                workflow_id = f"routing-perf-{i % 10}"  # 10 different workflows
                
                request_json = {
                    "model": "llama",
                    "prompt": f"Test request {i}",
                    "workflow_metadata": {
                        "workflow_id": workflow_id,
                        "agent_id": f"agent-{i}"
                    }
                }
                
                start_time = time.time()
                url = await router.route_request(endpoints, engine_stats, request_stats, request, request_json)
                routing_time = time.time() - start_time
                
                routing_times.append(routing_time)
                assert url in [ep.url for ep in endpoints]
            
            # Performance assertions
            avg_routing_time = statistics.mean(routing_times)
            p95_routing_time = statistics.quantiles(routing_times, n=20)[18] if len(routing_times) >= 20 else max(routing_times)
            
            # Routing decisions should be very fast (< 10ms average, < 50ms P95)
            assert avg_routing_time < 0.01, f"Average routing time {avg_routing_time*1000:.2f}ms exceeds 10ms threshold"
            assert p95_routing_time < 0.05, f"P95 routing time {p95_routing_time*1000:.2f}ms exceeds 50ms threshold"
            
            print(f"Routing performance: avg={avg_routing_time*1000:.2f}ms, p95={p95_routing_time*1000:.2f}ms")
            
        finally:
            await router.stop()
    
    @pytest.mark.asyncio
    @pytest.mark.performance
    async def test_concurrent_workflow_performance(self):
        """Test performance under concurrent workflow load."""
        workflow_manager = WorkflowContextManager()
        message_queue = WorkflowMessageQueue()
        
        await workflow_manager.start()
        await message_queue.start()
        
        try:
            num_concurrent_workflows = 20
            agents_per_workflow = 5
            
            async def simulate_workflow(workflow_index: int):
                """Simulate a complete workflow execution."""
                workflow_id = f"concurrent-{workflow_index}"
                start_time = time.time()
                
                # Register multiple agents for this workflow
                for agent_index in range(agents_per_workflow):
                    metadata = WorkflowMetadata(
                        workflow_id=workflow_id,
                        agent_id=f"agent-{agent_index}"
                    )
                    context = await workflow_manager.register_workflow(workflow_id, metadata)
                    assert context is not None
                
                # Send messages between agents
                for i in range(agents_per_workflow - 1):
                    message = AgentMessage(
                        workflow_id=workflow_id,
                        source_agent=f"agent-{i}",
                        target_agent=f"agent-{i+1}",
                        payload={"data": f"message-{i}"}
                    )
                    success = await message_queue.send_message(message)
                    assert success
                
                # Receive messages
                for i in range(1, agents_per_workflow):
                    messages = await message_queue.receive_messages(
                        workflow_id=workflow_id,
                        agent_id=f"agent-{i}",
                        timeout=1.0
                    )
                    assert len(messages) >= 1
                
                return time.time() - start_time
            
            # Run concurrent workflows
            start_time = time.time()
            tasks = [simulate_workflow(i) for i in range(num_concurrent_workflows)]
            workflow_times = await asyncio.gather(*tasks)
            total_time = time.time() - start_time
            
            # Performance assertions
            avg_workflow_time = statistics.mean(workflow_times)
            max_workflow_time = max(workflow_times)
            
            # Concurrent execution should be efficient
            assert total_time < 10.0, f"Total concurrent execution time {total_time:.2f}s exceeds 10s threshold"
            assert avg_workflow_time < 5.0, f"Average workflow time {avg_workflow_time:.2f}s exceeds 5s threshold"
            assert max_workflow_time < 10.0, f"Max workflow time {max_workflow_time:.2f}s exceeds 10s threshold"
            
            print(f"Concurrent performance: total={total_time:.2f}s, avg_workflow={avg_workflow_time:.2f}s")
            
        finally:
            await workflow_manager.stop()
            await message_queue.stop()


class TestWorkflowStressTests:
    """Stress tests for extreme conditions."""
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_maximum_concurrent_workflows(self):
        """Test behavior at maximum concurrent workflow limit."""
        max_workflows = 50  # Reduced for testing
        workflow_manager = WorkflowContextManager(max_workflows=max_workflows)
        
        await workflow_manager.start()
        
        try:
            # Create workflows up to the limit
            workflow_ids = []
            for i in range(max_workflows):
                workflow_id = f"stress-max-{i}"
                metadata = WorkflowMetadata(workflow_id=workflow_id, agent_id=f"agent-{i}")
                context = await workflow_manager.register_workflow(workflow_id, metadata)
                assert context is not None
                workflow_ids.append(workflow_id)
            
            # All workflows should be registered
            assert workflow_manager.total_workflows_created == max_workflows
            
            # Try to create one more (should still work but may trigger cleanup)
            overflow_workflow = f"stress-overflow"
            metadata = WorkflowMetadata(workflow_id=overflow_workflow, agent_id="overflow-agent")
            context = await workflow_manager.register_workflow(overflow_workflow, metadata)
            
            # Should handle gracefully (either accept or reject cleanly)
            if context is not None:
                print("Overflow workflow accepted (cleanup occurred)")
            else:
                print("Overflow workflow rejected (limit enforced)")
            
        finally:
            await workflow_manager.stop()
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_message_queue_saturation(self):
        """Test message queue behavior under saturation."""
        small_queue_size = 100
        message_queue = WorkflowMessageQueue(max_queue_size=small_queue_size)
        
        await message_queue.start()
        
        try:
            workflow_id = f"stress-saturation-{uuid.uuid4().hex[:8]}"
            
            # Try to send more messages than queue capacity
            overflow_messages = small_queue_size * 2
            successful_sends = 0
            failed_sends = 0
            
            for i in range(overflow_messages):
                message = AgentMessage(
                    workflow_id=workflow_id,
                    source_agent="stress-sender",
                    target_agent="stress-receiver",
                    payload={"data": f"stress-message-{i}"}
                )
                
                success = await message_queue.send_message(message)
                if success:
                    successful_sends += 1
                else:
                    failed_sends += 1
            
            # Should handle overflow gracefully
            assert successful_sends > 0, "No messages were sent successfully"
            assert successful_sends <= small_queue_size, f"More messages sent ({successful_sends}) than queue size ({small_queue_size})"
            
            # Verify we can still receive messages
            received_messages = await message_queue.receive_messages(
                workflow_id=workflow_id,
                agent_id="stress-receiver",
                timeout=2.0,
                max_messages=small_queue_size
            )
            
            assert len(received_messages) == successful_sends
            
            print(f"Saturation test: {successful_sends} sent, {failed_sends} failed, {len(received_messages)} received")
            
        finally:
            await message_queue.stop()
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_rapid_workflow_cycling(self):
        """Test rapid creation and deletion of workflows."""
        workflow_manager = WorkflowContextManager(ttl=1, cleanup_interval=0.5)  # Fast cleanup
        
        await workflow_manager.start()
        
        try:
            cycles = 20
            workflows_per_cycle = 10
            
            for cycle in range(cycles):
                cycle_start = time.time()
                
                # Create workflows rapidly
                workflow_ids = []
                for i in range(workflows_per_cycle):
                    workflow_id = f"rapid-cycle-{cycle}-{i}"
                    metadata = WorkflowMetadata(workflow_id=workflow_id, agent_id=f"agent-{i}")
                    context = await workflow_manager.register_workflow(workflow_id, metadata)
                    assert context is not None
                    workflow_ids.append(workflow_id)
                
                cycle_time = time.time() - cycle_start
                
                # Should create workflows quickly
                assert cycle_time < 1.0, f"Cycle {cycle} took {cycle_time:.2f}s, exceeds 1s threshold"
                
                # Wait for cleanup to occur
                await asyncio.sleep(1.5)
            
            # System should remain stable
            print(f"Rapid cycling completed: {cycles} cycles of {workflows_per_cycle} workflows each")
            
        finally:
            await workflow_manager.stop()


class TestWorkflowMemoryUsage:
    """Memory usage and leak detection tests."""
    
    @pytest.mark.asyncio
    @pytest.mark.memory
    async def test_workflow_context_cleanup(self):
        """Test that workflow contexts are properly cleaned up."""
        workflow_manager = WorkflowContextManager(ttl=1, cleanup_interval=0.5)
        
        await workflow_manager.start()
        
        try:
            initial_workflows = workflow_manager.total_workflows_created
            
            # Create many workflows
            num_workflows = 50
            for i in range(num_workflows):
                workflow_id = f"cleanup-test-{i}"
                metadata = WorkflowMetadata(workflow_id=workflow_id, agent_id=f"agent-{i}")
                await workflow_manager.register_workflow(workflow_id, metadata)
            
            assert workflow_manager.total_workflows_created == initial_workflows + num_workflows
            
            # Wait for cleanup
            await asyncio.sleep(2.0)
            
            # Workflows should be cleaned up
            assert workflow_manager.total_workflows_expired > 0
            
            # Verify no memory leaks by checking internal structures
            # (This is a simplified check - in production you'd use memory profiling tools)
            active_count = len([wf for wf in workflow_manager._workflows.values() if wf.is_active(ttl=1)])
            assert active_count == 0, f"Found {active_count} workflows that should have been cleaned up"
            
        finally:
            await workflow_manager.stop()
    
    @pytest.mark.asyncio
    @pytest.mark.memory  
    async def test_message_queue_memory_cleanup(self):
        """Test that message queues clean up expired messages."""
        message_queue = WorkflowMessageQueue()
        
        await message_queue.start()
        
        try:
            workflow_id = f"memory-cleanup-{uuid.uuid4().hex[:8]}"
            
            # Send messages with short TTL
            num_messages = 100
            for i in range(num_messages):
                message = AgentMessage(
                    workflow_id=workflow_id,
                    source_agent="memory-sender",
                    target_agent="memory-receiver",
                    payload={"data": f"memory-test-{i}"},
                    ttl=1  # Short TTL
                )
                success = await message_queue.send_message(message)
                assert success
            
            # Verify messages are there initially
            messages = await message_queue.receive_messages(
                workflow_id=workflow_id,
                agent_id="memory-receiver",
                timeout=0.1,
                max_messages=num_messages
            )
            assert len(messages) == num_messages
            
            # Wait for TTL expiration
            await asyncio.sleep(2.0)
            
            # Try to receive again - should get no messages (expired)
            expired_messages = await message_queue.receive_messages(
                workflow_id=workflow_id,
                agent_id="memory-receiver",
                timeout=0.1
            )
            assert len(expired_messages) == 0, f"Found {len(expired_messages)} messages that should have expired"
            
        finally:
            await message_queue.stop()