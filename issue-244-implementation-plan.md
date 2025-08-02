# Production-Stack Issue #244 Implementation Plan

## Issue: Optimize vLLM production-stack for agentic workflows via KV-cache reuse and context-aware routing

## 구현 범위

Production-stack은 vLLM 위의 orchestration layer로서 multi-agent 최적화를 구현하기에 완벽한 위치입니다.

## Phase 1: Core Infrastructure (Week 1-2)

### 1.1 Workflow Metadata 추가

**File: `src/vllm_router/protocols.py`**
```python
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class WorkflowMetadata(BaseModel):
    """Metadata for multi-agent workflows"""
    workflow_id: Optional[str] = Field(None, description="Unique workflow identifier")
    agent_id: Optional[str] = Field(None, description="Agent identifier within workflow")
    parent_request_id: Optional[str] = Field(None, description="Parent request ID for tracing")
    workflow_priority: float = Field(1.0, description="Workflow priority for scheduling")
    context_sharing_strategy: str = Field("auto", description="auto|broadcast|selective|none")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

class EnhancedCompletionRequest(BaseModel):
    """Extended completion request with workflow support"""
    # Existing fields...
    model: str
    prompt: str
    max_tokens: int
    
    # Workflow fields
    workflow_metadata: Optional[WorkflowMetadata] = None
```

### 1.2 Workflow Context Manager

**File: `src/vllm_router/services/workflow_service/workflow_manager.py`**
```python
import asyncio
from typing import Dict, List, Optional, Set
from collections import defaultdict
import time

class WorkflowContextManager:
    """Manages workflow contexts and agent coordination"""
    
    def __init__(self, ttl: int = 3600):
        self.workflows: Dict[str, WorkflowContext] = {}
        self.workflow_instances: Dict[str, str] = {}  # workflow_id -> instance_url
        self.agent_instances: Dict[tuple, str] = {}  # (workflow_id, agent_id) -> instance_url
        self.workflow_ttl = ttl
        self._cleanup_task = None
        
    async def start(self):
        """Start background cleanup task"""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        
    async def register_workflow(self, workflow_id: str, metadata: WorkflowMetadata):
        """Register a new workflow"""
        self.workflows[workflow_id] = WorkflowContext(
            workflow_id=workflow_id,
            created_at=time.time(),
            metadata=metadata
        )
        
    async def assign_instance(
        self, 
        workflow_id: str, 
        agent_id: Optional[str],
        available_instances: List[str]
    ) -> str:
        """Assign instance with workflow affinity"""
        # Check if workflow already assigned
        if workflow_id in self.workflow_instances:
            return self.workflow_instances[workflow_id]
            
        # Check for agent-specific assignment
        if agent_id and (workflow_id, agent_id) in self.agent_instances:
            return self.agent_instances[(workflow_id, agent_id)]
            
        # Find best instance based on load and cache
        best_instance = await self._find_best_instance(
            workflow_id, available_instances
        )
        
        # Store assignment
        self.workflow_instances[workflow_id] = best_instance
        if agent_id:
            self.agent_instances[(workflow_id, agent_id)] = best_instance
            
        return best_instance
```

### 1.3 Enhanced Router

**File: `src/vllm_router/routers/workflow_aware_router.py`**
```python
from typing import Dict, List, Optional
import logging

from vllm_router.routers.routing_logic import KvawareRouter
from vllm_router.services.workflow_service.workflow_manager import WorkflowContextManager

logger = logging.getLogger(__name__)

class WorkflowAwareRouter(KvawareRouter):
    """Router with workflow-aware capabilities"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.workflow_manager = WorkflowContextManager()
        self.workflow_cache_hits = 0
        self.total_workflow_requests = 0
        
    async def start(self):
        """Start router and workflow manager"""
        await super().start_kv_manager()
        await self.workflow_manager.start()
        
    async def route_request(
        self,
        endpoints,
        engine_stats,
        request_stats,
        request,
        request_json,
    ):
        """Route with workflow awareness"""
        
        # Extract workflow metadata
        workflow_metadata = request_json.get("workflow_metadata")
        
        if not workflow_metadata or not workflow_metadata.get("workflow_id"):
            # Fall back to parent routing
            return await super().route_request(
                endpoints, engine_stats, request_stats, request, request_json
            )
            
        workflow_id = workflow_metadata["workflow_id"]
        agent_id = workflow_metadata.get("agent_id")
        
        self.total_workflow_requests += 1
        
        # Register workflow if new
        if workflow_id not in self.workflow_manager.workflows:
            await self.workflow_manager.register_workflow(
                workflow_id, workflow_metadata
            )
        
        # Get instance assignment
        available_urls = [e.url for e in endpoints]
        assigned_instance = await self.workflow_manager.assign_instance(
            workflow_id, agent_id, available_urls
        )
        
        # Check if we can benefit from KV cache
        if await self._check_cache_benefit(workflow_id, request_json):
            self.workflow_cache_hits += 1
            
        logger.info(
            f"Routing workflow {workflow_id} agent {agent_id} to {assigned_instance}"
        )
        
        return assigned_instance
```

## Phase 2: A2A Communication (Week 2-3)

### 2.1 Message Queue Service

**File: `src/vllm_router/services/workflow_service/message_queue.py`**
```python
import asyncio
from typing import Dict, List, Optional
from collections import defaultdict
import uuid
import time

class AgentMessage:
    """Message between agents"""
    def __init__(
        self,
        source_agent: str,
        target_agent: str,
        workflow_id: str,
        payload: Dict,
        message_type: str = "data"
    ):
        self.id = str(uuid.uuid4())
        self.source_agent = source_agent
        self.target_agent = target_agent
        self.workflow_id = workflow_id
        self.payload = payload
        self.message_type = message_type
        self.timestamp = time.time()

class WorkflowMessageQueue:
    """Message queue for agent communication"""
    
    def __init__(self, max_queue_size: int = 1000):
        self.queues: Dict[tuple, asyncio.Queue] = {}
        self.max_queue_size = max_queue_size
        self.message_count = 0
        
    async def send_message(self, message: AgentMessage):
        """Send message to agent"""
        key = (message.workflow_id, message.target_agent)
        
        if key not in self.queues:
            self.queues[key] = asyncio.Queue(maxsize=self.max_queue_size)
            
        await self.queues[key].put(message)
        self.message_count += 1
        
    async def receive_messages(
        self,
        workflow_id: str,
        agent_id: str,
        timeout: Optional[float] = None
    ) -> List[AgentMessage]:
        """Receive messages for agent"""
        key = (workflow_id, agent_id)
        
        if key not in self.queues:
            return []
            
        messages = []
        queue = self.queues[key]
        
        try:
            # Get all available messages
            while not queue.empty():
                message = await asyncio.wait_for(
                    queue.get(), 
                    timeout=timeout or 0.1
                )
                messages.append(message)
                
                # Limit batch size
                if len(messages) >= 100:
                    break
                    
        except asyncio.TimeoutError:
            pass
            
        return messages
```

### 2.2 A2A API Endpoints

**File: `src/vllm_router/routers/workflow_router.py`**
```python
from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import List, Optional

router = APIRouter(prefix="/v1/workflows")

@router.post("/{workflow_id}/messages")
async def send_agent_message(
    workflow_id: str,
    source_agent: str,
    target_agent: str,
    payload: dict,
    message_type: str = "data"
):
    """Send message between agents"""
    
    message = AgentMessage(
        source_agent=source_agent,
        target_agent=target_agent,
        workflow_id=workflow_id,
        payload=payload,
        message_type=message_type
    )
    
    await app.state.message_queue.send_message(message)
    
    return {
        "message_id": message.id,
        "status": "sent",
        "timestamp": message.timestamp
    }

@router.get("/{workflow_id}/agents/{agent_id}/messages")
async def get_agent_messages(
    workflow_id: str,
    agent_id: str,
    timeout: float = 1.0
):
    """Get pending messages for agent"""
    
    messages = await app.state.message_queue.receive_messages(
        workflow_id, agent_id, timeout
    )
    
    return {
        "messages": [
            {
                "id": msg.id,
                "source": msg.source_agent,
                "payload": msg.payload,
                "type": msg.message_type,
                "timestamp": msg.timestamp
            }
            for msg in messages
        ],
        "count": len(messages)
    }

@router.get("/{workflow_id}/status")
async def get_workflow_status(workflow_id: str):
    """Get workflow status and metrics"""
    
    if workflow_id not in app.state.workflow_manager.workflows:
        raise HTTPException(404, "Workflow not found")
        
    workflow = app.state.workflow_manager.workflows[workflow_id]
    
    return {
        "workflow_id": workflow_id,
        "created_at": workflow.created_at,
        "active_agents": len(workflow.active_agents),
        "total_requests": workflow.total_requests,
        "cache_hits": workflow.cache_hits,
        "cache_hit_rate": workflow.get_cache_hit_rate()
    }
```

## Phase 3: Integration & Testing (Week 3-4)

### 3.1 Update Main Router

**File: `src/vllm_router/routers/main_router.py`**
```python
# Add to existing imports
from vllm_router.routers.workflow_router import router as workflow_router

# Add to router setup
app.include_router(workflow_router)

# Update request handling
async def handle_completion_request(request: Request):
    """Handle completion request with workflow support"""
    
    request_json = await request.json()
    
    # Check for workflow metadata
    if "workflow_metadata" in request_json:
        # Use workflow-aware routing
        router = app.state.workflow_router
    else:
        # Use standard routing
        router = app.state.router
        
    # Route and process request
    backend_url = await router.route_request(
        endpoints, engine_stats, request_stats, request, request_json
    )
    
    return await process_request(request, backend_url)
```

### 3.2 Configuration

**File: `helm/values.yaml`**
```yaml
router:
  # Existing config...
  
  # Workflow configuration
  workflowSupport:
    enabled: true
    ttl: 3600  # Workflow TTL in seconds
    maxWorkflows: 1000
    messageQueue:
      enabled: true
      maxQueueSize: 1000
    routing:
      strategy: "workflow_aware"  # or "kvaware", "prefixaware"
      batchingPreference: 0.8  # Prefer same workflow
      cacheAffinityWeight: 0.7
```

### 3.3 Tests

**File: `src/tests/test_workflow_routing.py`**
```python
import pytest
import asyncio
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_workflow_routing():
    """Test workflow-aware routing"""
    
    async with AsyncClient(base_url="http://localhost:8000") as client:
        workflow_id = "test-workflow-123"
        
        # First agent request
        response1 = await client.post(
            "/v1/completions",
            json={
                "model": "llama",
                "prompt": "Analyze data",
                "max_tokens": 100,
                "workflow_metadata": {
                    "workflow_id": workflow_id,
                    "agent_id": "analyzer"
                }
            }
        )
        assert response1.status_code == 200
        
        # Second agent request (should route to same instance)
        response2 = await client.post(
            "/v1/completions",
            json={
                "model": "llama",
                "prompt": "Summarize analysis",
                "max_tokens": 100,
                "workflow_metadata": {
                    "workflow_id": workflow_id,
                    "agent_id": "summarizer"
                }
            }
        )
        assert response2.status_code == 200
        
        # Check workflow status
        status = await client.get(f"/v1/workflows/{workflow_id}/status")
        assert status.json()["active_agents"] >= 2

@pytest.mark.asyncio
async def test_agent_communication():
    """Test A2A messaging"""
    
    async with AsyncClient(base_url="http://localhost:8000") as client:
        workflow_id = "test-workflow-456"
        
        # Send message
        await client.post(
            f"/v1/workflows/{workflow_id}/messages",
            json={
                "source_agent": "agent1",
                "target_agent": "agent2",
                "payload": {"data": "test message"}
            }
        )
        
        # Receive message
        response = await client.get(
            f"/v1/workflows/{workflow_id}/agents/agent2/messages"
        )
        
        messages = response.json()["messages"]
        assert len(messages) == 1
        assert messages[0]["payload"]["data"] == "test message"
```

## Phase 4: Benchmarking & Optimization (Week 4-5)

### 4.1 Benchmark Suite

**File: `benchmarks/workflow_benchmark.py`**
```python
import asyncio
import time
import statistics
from typing import List, Dict

class WorkflowBenchmark:
    """Benchmark workflow performance"""
    
    async def benchmark_sequential_workflow(self, num_agents: int = 5):
        """Benchmark sequential agent execution"""
        
        workflow_id = f"bench-seq-{time.time()}"
        latencies = []
        
        for i in range(num_agents):
            start = time.time()
            
            response = await self.client.post(
                "/v1/completions",
                json={
                    "model": "llama",
                    "prompt": f"Agent {i} task",
                    "max_tokens": 100,
                    "workflow_metadata": {
                        "workflow_id": workflow_id,
                        "agent_id": f"agent-{i}"
                    }
                }
            )
            
            latency = time.time() - start
            latencies.append(latency)
            
        return {
            "type": "sequential",
            "num_agents": num_agents,
            "total_time": sum(latencies),
            "avg_latency": statistics.mean(latencies),
            "p95_latency": statistics.quantiles(latencies, n=20)[18]
        }
    
    async def benchmark_parallel_workflow(self, num_agents: int = 5):
        """Benchmark parallel agent execution"""
        
        workflow_id = f"bench-par-{time.time()}"
        
        async def agent_task(agent_id: str):
            start = time.time()
            response = await self.client.post(
                "/v1/completions",
                json={
                    "model": "llama",
                    "prompt": f"Agent {agent_id} task",
                    "max_tokens": 100,
                    "workflow_metadata": {
                        "workflow_id": workflow_id,
                        "agent_id": agent_id
                    }
                }
            )
            return time.time() - start
        
        start_time = time.time()
        latencies = await asyncio.gather(*[
            agent_task(f"agent-{i}") for i in range(num_agents)
        ])
        total_time = time.time() - start_time
        
        return {
            "type": "parallel",
            "num_agents": num_agents,
            "total_time": total_time,
            "avg_latency": statistics.mean(latencies),
            "speedup": sum(latencies) / total_time
        }
    
    async def benchmark_cache_efficiency(self, context_size: int = 1000):
        """Benchmark KV-cache reuse"""
        
        workflow_id = f"bench-cache-{time.time()}"
        shared_context = "data " * context_size
        
        # First request (cold cache)
        start1 = time.time()
        await self.client.post(
            "/v1/completions",
            json={
                "model": "llama",
                "prompt": f"{shared_context}\nAnalyze this.",
                "max_tokens": 50,
                "workflow_metadata": {
                    "workflow_id": workflow_id,
                    "agent_id": "agent-1"
                }
            }
        )
        cold_latency = time.time() - start1
        
        # Second request (warm cache)
        start2 = time.time()
        await self.client.post(
            "/v1/completions",
            json={
                "model": "llama",
                "prompt": f"{shared_context}\nSummarize this.",
                "max_tokens": 50,
                "workflow_metadata": {
                    "workflow_id": workflow_id,
                    "agent_id": "agent-2"
                }
            }
        )
        warm_latency = time.time() - start2
        
        return {
            "context_size": context_size,
            "cold_latency": cold_latency,
            "warm_latency": warm_latency,
            "cache_speedup": cold_latency / warm_latency,
            "saved_ms": (cold_latency - warm_latency) * 1000
        }
```

### 4.2 Metrics & Monitoring

**File: `src/vllm_router/services/metrics_service/workflow_metrics.py`**
```python
from prometheus_client import Counter, Histogram, Gauge

# Workflow metrics
workflow_requests = Counter(
    'vllm_workflow_requests_total',
    'Total workflow requests',
    ['workflow_id', 'agent_id']
)

workflow_cache_hits = Counter(
    'vllm_workflow_cache_hits_total',
    'Workflow cache hits',
    ['workflow_id']
)

workflow_latency = Histogram(
    'vllm_workflow_latency_seconds',
    'Workflow request latency',
    ['workflow_id', 'agent_id']
)

active_workflows = Gauge(
    'vllm_active_workflows',
    'Number of active workflows'
)

workflow_message_queue_size = Gauge(
    'vllm_workflow_message_queue_size',
    'Size of agent message queues',
    ['workflow_id', 'agent_id']
)

workflow_batch_efficiency = Gauge(
    'vllm_workflow_batch_efficiency',
    'Efficiency of workflow batching'
)
```

## Phase 5: Documentation & Examples (Week 5)

### 5.1 User Guide

**File: `docs/workflow-guide.md`**
```markdown
# Multi-Agent Workflow Guide

## Quick Start

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1")

# Define workflow
workflow_id = "analysis-workflow-123"

# Agent 1: Data Analyzer
response1 = client.completions.create(
    model="meta-llama/Llama-3.1-8B-Instruct",
    prompt="Analyze this sales data: [100, 200, 150, 300]",
    max_tokens=100,
    extra_body={
        "workflow_metadata": {
            "workflow_id": workflow_id,
            "agent_id": "analyzer"
        }
    }
)

# Agent 2: Report Generator (benefits from cache)
response2 = client.completions.create(
    model="meta-llama/Llama-3.1-8B-Instruct",
    prompt="Analyze this sales data: [100, 200, 150, 300]. Generate a report.",
    max_tokens=200,
    extra_body={
        "workflow_metadata": {
            "workflow_id": workflow_id,
            "agent_id": "reporter",
            "parent_request_id": response1.id
        }
    }
)
```

## A2A Communication

```python
# Send message between agents
await client.post(
    f"/v1/workflows/{workflow_id}/messages",
    json={
        "source_agent": "analyzer",
        "target_agent": "reporter",
        "payload": {
            "analysis_complete": True,
            "key_findings": ["trend up", "Q4 spike"]
        }
    }
)

# Receive messages
messages = await client.get(
    f"/v1/workflows/{workflow_id}/agents/reporter/messages"
)
```
```

## Deployment Timeline

1. **Week 1-2**: Core infrastructure (metadata, routing)
2. **Week 2-3**: A2A communication
3. **Week 3-4**: Testing and integration
4. **Week 4-5**: Benchmarking and optimization
5. **Week 5**: Documentation and examples

## Expected Impact

- **3-10x latency reduction** for multi-agent workflows
- **40-60% cache hit rate improvement**
- **25-40% GPU memory savings** through better sharing
- **Native support** for frameworks like LangChain, AutoGen, BeeAI

## Success Metrics

1. **Performance**: Benchmark results showing speedup
2. **Adoption**: Number of workflows using the feature
3. **Stability**: Error rate < 0.1%
4. **Scalability**: Support 1000+ concurrent workflows