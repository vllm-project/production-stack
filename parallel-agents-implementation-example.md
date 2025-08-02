# Parallel Agents Implementation Example

## Complete Working Example

### 1. Router Extension for Parallel Agents

```python
# File: /src/vllm_router/routers/parallel_workflow_router.py

import asyncio
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple
import json
import time

from .workflow_aware_router import WorkflowAwareRouter
from vllm_router.log import init_logger

logger = init_logger(__name__)

class ParallelWorkflowRouter(WorkflowAwareRouter):
    """
    Router supporting parallel agent execution and A2A communication
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # A2A message queues: (workflow_id, agent_id) -> messages
        self.agent_mailboxes: Dict[Tuple[str, str], asyncio.Queue] = {}
        
        # Track active agents per workflow
        self.active_agents: Dict[str, Set[str]] = defaultdict(set)
        
        # Synchronization barriers
        self.workflow_barriers: Dict[str, asyncio.Barrier] = {}
        
        # Agent execution status
        self.agent_status: Dict[Tuple[str, str], str] = {}
        
    async def register_agent(self, workflow_id: str, agent_id: str):
        """Register an agent in the workflow"""
        key = (workflow_id, agent_id)
        
        # Create mailbox if not exists
        if key not in self.agent_mailboxes:
            self.agent_mailboxes[key] = asyncio.Queue()
            
        # Track active agent
        self.active_agents[workflow_id].add(agent_id)
        self.agent_status[key] = "active"
        
        logger.info(f"Registered agent {agent_id} in workflow {workflow_id}")
        
    async def send_a2a_message(
        self, 
        workflow_id: str,
        source_agent: str,
        target_agent: str,
        message: Dict
    ):
        """Send message from one agent to another"""
        target_key = (workflow_id, target_agent)
        
        if target_key not in self.agent_mailboxes:
            await self.register_agent(workflow_id, target_agent)
            
        wrapped_message = {
            "source": source_agent,
            "target": target_agent,
            "timestamp": time.time(),
            "payload": message
        }
        
        await self.agent_mailboxes[target_key].put(wrapped_message)
        logger.debug(f"Sent A2A message: {source_agent} -> {target_agent}")
        
    async def receive_a2a_messages(
        self,
        workflow_id: str,
        agent_id: str,
        timeout: Optional[float] = None
    ) -> List[Dict]:
        """Receive pending messages for an agent"""
        key = (workflow_id, agent_id)
        messages = []
        
        if key not in self.agent_mailboxes:
            return messages
            
        try:
            while True:
                # Non-blocking get
                message = await asyncio.wait_for(
                    self.agent_mailboxes[key].get(),
                    timeout=0.1 if timeout is None else timeout
                )
                messages.append(message)
                
                # Prevent infinite loop
                if len(messages) >= 100:
                    break
                    
        except asyncio.TimeoutError:
            pass
            
        return messages
    
    async def create_barrier(self, workflow_id: str, num_agents: int):
        """Create synchronization barrier for parallel agents"""
        if workflow_id not in self.workflow_barriers:
            self.workflow_barriers[workflow_id] = asyncio.Barrier(num_agents)
            
    async def wait_at_barrier(self, workflow_id: str, agent_id: str):
        """Wait for all agents at barrier"""
        if workflow_id in self.workflow_barriers:
            logger.info(f"Agent {agent_id} waiting at barrier")
            await self.workflow_barriers[workflow_id].wait()
            logger.info(f"Agent {agent_id} passed barrier")
            
    async def route_request(
        self,
        endpoints,
        engine_stats,
        request_stats,
        request,
        request_json,
        workflow_context: Optional[Dict] = None
    ):
        """Enhanced routing for parallel agents"""
        
        if not workflow_context:
            # Fallback to parent routing
            return await super().route_request(
                endpoints, engine_stats, request_stats, request, request_json
            )
            
        workflow_id = workflow_context.get("workflow_id")
        agent_id = workflow_context.get("agent_id")
        execution_mode = workflow_context.get("execution_mode", "sequential")
        
        # Register agent if new
        if workflow_id and agent_id:
            await self.register_agent(workflow_id, agent_id)
            
            # Check for pending A2A messages
            messages = await self.receive_a2a_messages(workflow_id, agent_id)
            if messages:
                # Inject messages into request
                request_json["a2a_messages"] = messages
                logger.info(f"Injected {len(messages)} A2A messages for agent {agent_id}")
        
        # Route based on execution mode
        if execution_mode == "parallel":
            return await self._route_parallel_request(
                endpoints, workflow_id, agent_id
            )
        else:
            return await super().route_request(
                endpoints, engine_stats, request_stats, request, request_json, workflow_context
            )
            
    async def _route_parallel_request(
        self,
        endpoints,
        workflow_id: str,
        agent_id: str
    ) -> str:
        """Route requests for parallel agents with load balancing"""
        
        # Count agents per instance for this workflow
        agent_distribution = defaultdict(int)
        
        for (wf_id, ag_id), status in self.agent_status.items():
            if wf_id == workflow_id and status == "active":
                # Find which instance handles this agent
                instance = self.workflow_to_instance.get(f"{wf_id}:{ag_id}")
                if instance:
                    agent_distribution[instance] += 1
                    
        # Find instance with minimum agents for load balancing
        min_agents = float('inf')
        best_instance = None
        
        for endpoint in endpoints:
            url = endpoint.url
            agent_count = agent_distribution.get(url, 0)
            
            # Prefer instances already handling this workflow (cache benefit)
            if workflow_id in self.instance_workflows.get(url, set()):
                agent_count *= 0.8  # 20% preference
                
            if agent_count < min_agents:
                min_agents = agent_count
                best_instance = url
                
        # Map this specific agent to instance
        self.workflow_to_instance[f"{workflow_id}:{agent_id}"] = best_instance
        
        logger.info(f"Routed parallel agent {agent_id} to {best_instance} (load: {min_agents})")
        return best_instance
```

### 2. API Extensions for A2A Communication

```python
# File: /src/vllm_router/routers/a2a_router.py

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

router = APIRouter(prefix="/v1/workflows")

class A2AMessage(BaseModel):
    source_agent: str
    target_agent: str
    message_type: str = "data"
    payload: Dict[str, Any]
    
class A2ASyncRequest(BaseModel):
    agent_id: str
    sync_point: str = "default"
    data: Optional[Dict[str, Any]] = None

@router.post("/{workflow_id}/agents/{agent_id}/send")
async def send_a2a_message(
    workflow_id: str,
    agent_id: str,
    message: A2AMessage,
    background_tasks: BackgroundTasks
):
    """Send A2A message"""
    
    # Validate source agent
    if message.source_agent != agent_id:
        raise HTTPException(400, "Source agent mismatch")
        
    # Get router instance
    router = get_routing_logic()
    if not hasattr(router, 'send_a2a_message'):
        raise HTTPException(501, "A2A communication not supported")
        
    # Send message
    await router.send_a2a_message(
        workflow_id,
        message.source_agent,
        message.target_agent,
        message.payload
    )
    
    return {"status": "sent", "timestamp": time.time()}

@router.get("/{workflow_id}/agents/{agent_id}/messages")
async def receive_a2a_messages(
    workflow_id: str,
    agent_id: str,
    timeout: Optional[float] = 1.0,
    max_messages: int = 100
):
    """Receive pending A2A messages"""
    
    router = get_routing_logic()
    if not hasattr(router, 'receive_a2a_messages'):
        raise HTTPException(501, "A2A communication not supported")
        
    messages = await router.receive_a2a_messages(
        workflow_id, agent_id, timeout
    )
    
    return {
        "messages": messages[:max_messages],
        "count": len(messages),
        "has_more": len(messages) > max_messages
    }

@router.post("/{workflow_id}/sync/barrier")
async def sync_barrier(
    workflow_id: str,
    request: A2ASyncRequest
):
    """Synchronization barrier for parallel agents"""
    
    router = get_routing_logic()
    if not hasattr(router, 'wait_at_barrier'):
        raise HTTPException(501, "Synchronization not supported")
        
    await router.wait_at_barrier(workflow_id, request.agent_id)
    
    return {
        "status": "synchronized",
        "agent_id": request.agent_id,
        "sync_point": request.sync_point
    }
```

### 3. Client SDK for Parallel Agents

```python
# File: /src/vllm_router/clients/parallel_agent_client.py

import asyncio
import httpx
from typing import Dict, List, Optional, Any
import json

class ParallelAgentClient:
    """Client for parallel agent workflows with A2A communication"""
    
    def __init__(self, base_url: str = "http://localhost:30080"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0)
        
    async def execute_agent(
        self,
        workflow_id: str,
        agent_id: str,
        model: str,
        prompt: str,
        max_tokens: int = 100,
        execution_mode: str = "parallel",
        a2a_handler = None
    ) -> Dict:
        """Execute an agent with A2A support"""
        
        headers = {
            "X-Workflow-Id": workflow_id,
            "X-Agent-Id": agent_id
        }
        
        request_body = {
            "model": model,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "workflow_id": workflow_id,
            "agent_id": agent_id,
            "execution_mode": execution_mode
        }
        
        # Main completion request
        response = await self.client.post(
            f"{self.base_url}/v1/completions",
            headers=headers,
            json=request_body
        )
        
        result = response.json()
        
        # Process any A2A messages in response
        if "a2a_messages" in result:
            for msg in result["a2a_messages"]:
                if a2a_handler:
                    await a2a_handler(msg)
                    
        return result
        
    async def send_message(
        self,
        workflow_id: str,
        source_agent: str,
        target_agent: str,
        payload: Dict
    ):
        """Send A2A message"""
        
        message = {
            "source_agent": source_agent,
            "target_agent": target_agent,
            "message_type": "data",
            "payload": payload
        }
        
        await self.client.post(
            f"{self.base_url}/v1/workflows/{workflow_id}/agents/{source_agent}/send",
            json=message
        )
        
    async def receive_messages(
        self,
        workflow_id: str,
        agent_id: str,
        timeout: float = 1.0
    ) -> List[Dict]:
        """Receive A2A messages"""
        
        response = await self.client.get(
            f"{self.base_url}/v1/workflows/{workflow_id}/agents/{agent_id}/messages",
            params={"timeout": timeout}
        )
        
        return response.json()["messages"]
        
    async def wait_barrier(self, workflow_id: str, agent_id: str):
        """Wait at synchronization barrier"""
        
        await self.client.post(
            f"{self.base_url}/v1/workflows/{workflow_id}/sync/barrier",
            json={"agent_id": agent_id}
        )
```

### 4. Example: Multi-Agent Analysis Workflow

```python
# File: /examples/parallel_multi_agent_analysis.py

import asyncio
from vllm_router.clients.parallel_agent_client import ParallelAgentClient

async def data_analyzer_agent(
    client: ParallelAgentClient,
    workflow_id: str,
    agent_id: str,
    data_segment: str
):
    """Individual data analyzer agent"""
    
    # Analyze data segment
    result = await client.execute_agent(
        workflow_id=workflow_id,
        agent_id=agent_id,
        model="meta-llama/Llama-3.1-8B-Instruct",
        prompt=f"Analyze this data segment and extract key insights: {data_segment}",
        max_tokens=200,
        execution_mode="parallel"
    )
    
    # Extract insights
    insights = result["choices"][0]["text"]
    
    # Send results to aggregator
    await client.send_message(
        workflow_id=workflow_id,
        source_agent=agent_id,
        target_agent="aggregator",
        payload={
            "agent_id": agent_id,
            "insights": insights,
            "data_segment": data_segment[:100]  # Preview
        }
    )
    
    # Wait for all analyzers to complete
    await client.wait_barrier(workflow_id, agent_id)
    
    return insights

async def aggregator_agent(
    client: ParallelAgentClient,
    workflow_id: str,
    num_analyzers: int
):
    """Aggregator agent that combines results"""
    
    # Collect results from all analyzers
    all_insights = []
    
    for i in range(num_analyzers):
        messages = await client.receive_messages(
            workflow_id=workflow_id,
            agent_id="aggregator",
            timeout=30.0
        )
        
        for msg in messages:
            all_insights.append(msg["payload"]["insights"])
            
    # Synthesize findings
    synthesis_prompt = f"""
    Synthesize these insights from {num_analyzers} parallel analyses:
    
    {json.dumps(all_insights, indent=2)}
    
    Provide a comprehensive summary with key findings and patterns.
    """
    
    result = await client.execute_agent(
        workflow_id=workflow_id,
        agent_id="aggregator",
        model="meta-llama/Llama-3.1-8B-Instruct",
        prompt=synthesis_prompt,
        max_tokens=500
    )
    
    return result["choices"][0]["text"]

async def run_parallel_analysis(data_segments: List[str]):
    """Run parallel multi-agent analysis"""
    
    client = ParallelAgentClient()
    workflow_id = f"analysis-{int(time.time())}"
    
    # Create analyzer tasks
    analyzer_tasks = []
    for i, segment in enumerate(data_segments):
        task = data_analyzer_agent(
            client,
            workflow_id,
            f"analyzer-{i}",
            segment
        )
        analyzer_tasks.append(task)
        
    # Create aggregator task
    aggregator_task = aggregator_agent(
        client,
        workflow_id,
        len(data_segments)
    )
    
    # Run all agents in parallel
    analyzer_results = await asyncio.gather(*analyzer_tasks)
    aggregated_result = await aggregator_task
    
    return {
        "individual_insights": analyzer_results,
        "synthesized_report": aggregated_result
    }

# Example usage
if __name__ == "__main__":
    data = [
        "Q1 revenue increased by 15%...",
        "Customer satisfaction scores improved...",
        "Market share grew in key segments..."
    ]
    
    result = asyncio.run(run_parallel_analysis(data))
    print(json.dumps(result, indent=2))
```

### 5. Testing Parallel Agents

```python
# File: /src/tests/test_parallel_agents.py

import pytest
import asyncio
from vllm_router.routers.parallel_workflow_router import ParallelWorkflowRouter

@pytest.mark.asyncio
async def test_a2a_communication():
    """Test agent-to-agent message passing"""
    
    router = ParallelWorkflowRouter(
        lmcache_controller_port=9000,
        session_key="x-user-id"
    )
    
    workflow_id = "test-workflow"
    
    # Register agents
    await router.register_agent(workflow_id, "agent-1")
    await router.register_agent(workflow_id, "agent-2")
    
    # Send message
    await router.send_a2a_message(
        workflow_id,
        "agent-1",
        "agent-2",
        {"data": "test message"}
    )
    
    # Receive message
    messages = await router.receive_a2a_messages(workflow_id, "agent-2")
    
    assert len(messages) == 1
    assert messages[0]["source"] == "agent-1"
    assert messages[0]["payload"]["data"] == "test message"

@pytest.mark.asyncio
async def test_parallel_routing():
    """Test parallel agent load distribution"""
    
    router = ParallelWorkflowRouter(
        lmcache_controller_port=9000,
        session_key="x-user-id"
    )
    
    endpoints = [
        EndpointInfo(url="http://vllm-1:8000", model_names=["llama"]),
        EndpointInfo(url="http://vllm-2:8000", model_names=["llama"]),
        EndpointInfo(url="http://vllm-3:8000", model_names=["llama"])
    ]
    
    workflow_id = "parallel-test"
    
    # Route multiple parallel agents
    assignments = {}
    for i in range(6):
        agent_id = f"agent-{i}"
        url = await router._route_parallel_request(
            endpoints, workflow_id, agent_id
        )
        assignments[agent_id] = url
        
    # Check load distribution
    instance_counts = {}
    for url in assignments.values():
        instance_counts[url] = instance_counts.get(url, 0) + 1
        
    # Should be evenly distributed
    assert max(instance_counts.values()) - min(instance_counts.values()) <= 1

@pytest.mark.asyncio
async def test_barrier_synchronization():
    """Test agent synchronization barrier"""
    
    router = ParallelWorkflowRouter(
        lmcache_controller_port=9000,
        session_key="x-user-id"
    )
    
    workflow_id = "sync-test"
    num_agents = 3
    
    # Create barrier
    await router.create_barrier(workflow_id, num_agents)
    
    # Track completion order
    completion_order = []
    
    async def agent_task(agent_id: str):
        await asyncio.sleep(0.1 * int(agent_id[-1]))  # Different delays
        await router.wait_at_barrier(workflow_id, agent_id)
        completion_order.append(agent_id)
        
    # Run agents
    tasks = [agent_task(f"agent-{i}") for i in range(num_agents)]
    await asyncio.gather(*tasks)
    
    # All should complete at same time despite different delays
    assert len(completion_order) == num_agents
```

## Performance Benchmarks

```python
# File: /benchmarks/parallel_agents_benchmark.py

async def benchmark_parallel_vs_sequential():
    """Compare parallel vs sequential agent execution"""
    
    # Test configuration
    num_agents = 10
    prompt_length = 100
    max_tokens = 50
    
    # Sequential execution
    start_time = time.time()
    for i in range(num_agents):
        await execute_agent_sequential(i, prompt_length, max_tokens)
    sequential_time = time.time() - start_time
    
    # Parallel execution
    start_time = time.time()
    tasks = [
        execute_agent_parallel(i, prompt_length, max_tokens)
        for i in range(num_agents)
    ]
    await asyncio.gather(*tasks)
    parallel_time = time.time() - start_time
    
    speedup = sequential_time / parallel_time
    
    print(f"Sequential: {sequential_time:.2f}s")
    print(f"Parallel: {parallel_time:.2f}s")
    print(f"Speedup: {speedup:.2f}x")
    
    return {
        "sequential_time": sequential_time,
        "parallel_time": parallel_time,
        "speedup": speedup,
        "efficiency": speedup / num_agents
    }
```