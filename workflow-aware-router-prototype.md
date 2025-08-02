# Workflow-Aware Router Prototype Implementation Plan

## Overview
This document outlines a concrete implementation plan for adding workflow-aware routing to vLLM production-stack.

## Step 1: API Extension

### 1.1 Update Request Processing
File: `/src/vllm_router/services/request_service/request.py`

```python
# Add after line 166
workflow_id = request.headers.get("X-Workflow-Id") or \
             request_json.get("workflow_id", None)
agent_id = request.headers.get("X-Agent-Id") or \
           request_json.get("agent_id", None)
parent_request_id = request.headers.get("X-Parent-Request-Id") or \
                    request_json.get("parent_request_id", None)

# Pass workflow context to router
workflow_context = {
    "workflow_id": workflow_id,
    "agent_id": agent_id,
    "parent_request_id": parent_request_id,
    "request_id": request_id
}
```

## Step 2: Create Workflow-Aware Router

### 2.1 New Router Class
File: `/src/vllm_router/routers/workflow_aware_router.py`

```python
from typing import Dict, Set, Optional
import time
from .routing_logic import KvawareRouter, RoutingInterface
from vllm_router.log import init_logger

logger = init_logger(__name__)

class WorkflowAwareRouter(KvawareRouter):
    """
    Routes requests based on workflow affinity and KV-cache availability.
    Extends KvawareRouter to add workflow-aware routing capabilities.
    """
    
    def __init__(
        self,
        lmcache_controller_port: int,
        session_key: str,
        kv_aware_threshold: int = 2000,
        workflow_ttl: int = 3600  # 1 hour default TTL
    ):
        super().__init__(lmcache_controller_port, session_key, kv_aware_threshold)
        self.workflow_to_instance: Dict[str, str] = {}
        self.workflow_last_access: Dict[str, float] = {}
        self.instance_workflows: Dict[str, Set[str]] = {}
        self.workflow_ttl = workflow_ttl
        
    def _cleanup_expired_workflows(self):
        """Remove expired workflow mappings"""
        current_time = time.time()
        expired_workflows = [
            wf_id for wf_id, last_access in self.workflow_last_access.items()
            if current_time - last_access > self.workflow_ttl
        ]
        
        for wf_id in expired_workflows:
            instance = self.workflow_to_instance.pop(wf_id, None)
            self.workflow_last_access.pop(wf_id, None)
            if instance and instance in self.instance_workflows:
                self.instance_workflows[instance].discard(wf_id)
                
    async def route_request(
        self,
        endpoints,
        engine_stats,
        request_stats,
        request,
        request_json,
        workflow_context: Optional[Dict] = None
    ):
        """Route with workflow awareness"""
        
        # Cleanup expired workflows periodically
        self._cleanup_expired_workflows()
        
        workflow_id = workflow_context.get("workflow_id") if workflow_context else None
        
        if workflow_id:
            # Check if workflow already mapped to an instance
            if workflow_id in self.workflow_to_instance:
                instance_url = self.workflow_to_instance[workflow_id]
                # Verify instance is still available
                if any(e.url == instance_url for e in endpoints):
                    self.workflow_last_access[workflow_id] = time.time()
                    logger.info(f"Routing workflow {workflow_id} to existing instance {instance_url}")
                    return instance_url
                else:
                    # Instance no longer available, remove mapping
                    self.workflow_to_instance.pop(workflow_id, None)
                    self.instance_workflows.get(instance_url, set()).discard(workflow_id)
        
        # Fall back to KV-aware routing
        selected_url = await super().route_request(
            endpoints, engine_stats, request_stats, request, request_json
        )
        
        # Map workflow to selected instance
        if workflow_id:
            self.workflow_to_instance[workflow_id] = selected_url
            self.workflow_last_access[workflow_id] = time.time()
            if selected_url not in self.instance_workflows:
                self.instance_workflows[selected_url] = set()
            self.instance_workflows[selected_url].add(workflow_id)
            logger.info(f"Mapped workflow {workflow_id} to instance {selected_url}")
            
        return selected_url
```

## Step 3: Update Routing Logic Integration

### 3.1 Add to RoutingLogic Enum
File: `/src/vllm_router/routers/routing_logic.py`

```python
class RoutingLogic(str, enum.Enum):
    ROUND_ROBIN = "roundrobin"
    SESSION_BASED = "session"
    KVAWARE = "kvaware"
    PREFIXAWARE = "prefixaware"
    DISAGGREGATED_PREFILL = "disaggregated_prefill"
    WORKFLOW_AWARE = "workflow_aware"  # Add this
```

### 3.2 Update initialize_routing_logic
```python
elif routing_logic == RoutingLogic.WORKFLOW_AWARE:
    logger.info("Initializing workflow-aware routing logic")
    from .workflow_aware_router import WorkflowAwareRouter
    router = WorkflowAwareRouter(
        kwargs.get("lmcache_controller_port"),
        kwargs.get("session_key"),
        kwargs.get("kv_aware_threshold"),
        kwargs.get("workflow_ttl", 3600)
    )
    router.start_kv_manager()
    return router
```

## Step 4: Add Workflow Metrics

### 4.1 Create Workflow Stats
File: `/src/vllm_router/stats/workflow_stats.py`

```python
from dataclasses import dataclass
from typing import Dict, Set
import time

@dataclass
class WorkflowStats:
    """Track workflow-level statistics"""
    workflow_id: str
    start_time: float
    last_access_time: float
    request_count: int = 0
    cache_hits: int = 0
    total_tokens: int = 0
    agents: Set[str] = None
    
    def __post_init__(self):
        if self.agents is None:
            self.agents = set()
            
    def update(self, agent_id: str, tokens: int, cache_hit: bool):
        self.last_access_time = time.time()
        self.request_count += 1
        self.total_tokens += tokens
        if agent_id:
            self.agents.add(agent_id)
        if cache_hit:
            self.cache_hits += 1
            
    @property
    def cache_hit_rate(self) -> float:
        return self.cache_hits / self.request_count if self.request_count > 0 else 0.0
        
    @property
    def duration(self) -> float:
        return self.last_access_time - self.start_time
```

## Step 5: Testing Implementation

### 5.1 Unit Test
File: `/src/tests/test_workflow_router.py`

```python
import pytest
import asyncio
from vllm_router.routers.workflow_aware_router import WorkflowAwareRouter
from vllm_router.service_discovery import EndpointInfo

@pytest.mark.asyncio
async def test_workflow_routing():
    """Test workflow-aware routing behavior"""
    
    # Setup
    router = WorkflowAwareRouter(
        lmcache_controller_port=9000,
        session_key="x-user-id",
        workflow_ttl=60
    )
    
    endpoints = [
        EndpointInfo(url="http://vllm-1:8000", model_names=["llama"]),
        EndpointInfo(url="http://vllm-2:8000", model_names=["llama"])
    ]
    
    # Test workflow affinity
    workflow_context = {
        "workflow_id": "test-workflow-123",
        "agent_id": "agent-1"
    }
    
    # First request
    url1 = await router.route_request(
        endpoints, {}, {}, None, {"prompt": "test"}, workflow_context
    )
    
    # Second request with same workflow
    url2 = await router.route_request(
        endpoints, {}, {}, None, {"prompt": "test2"}, workflow_context
    )
    
    # Should route to same instance
    assert url1 == url2
    assert "test-workflow-123" in router.workflow_to_instance
```

### 5.2 Integration Test Script
File: `/src/tests/test_workflow_integration.py`

```python
#!/usr/bin/env python3
import asyncio
import httpx
import json

async def test_workflow_routing():
    """Test workflow routing with real requests"""
    
    base_url = "http://localhost:30080"
    workflow_id = "test-workflow-001"
    
    headers = {
        "Content-Type": "application/json",
        "X-Workflow-Id": workflow_id
    }
    
    # Agent 1 request
    async with httpx.AsyncClient() as client:
        response1 = await client.post(
            f"{base_url}/v1/completions",
            headers={**headers, "X-Agent-Id": "agent-1"},
            json={
                "model": "meta-llama/Llama-3.1-8B-Instruct",
                "prompt": "What is machine learning?",
                "max_tokens": 50,
                "workflow_id": workflow_id,
                "agent_id": "agent-1"
            }
        )
        
        print(f"Agent 1 response: {response1.status_code}")
        
        # Agent 2 request (should reuse context)
        response2 = await client.post(
            f"{base_url}/v1/completions",
            headers={**headers, "X-Agent-Id": "agent-2"},
            json={
                "model": "meta-llama/Llama-3.1-8B-Instruct",
                "prompt": "What is machine learning? Can you explain it in simple terms?",
                "max_tokens": 100,
                "workflow_id": workflow_id,
                "agent_id": "agent-2"
            }
        )
        
        print(f"Agent 2 response: {response2.status_code}")

if __name__ == "__main__":
    asyncio.run(test_workflow_routing())
```

## Step 6: Configuration Updates

### 6.1 Add CLI Arguments
File: `/src/vllm_router/parsers/parser.py`

```python
# Add after line 193
parser.add_argument(
    "--workflow-ttl",
    type=int,
    default=3600,
    help="TTL for workflow-to-instance mappings in seconds (default: 3600)"
)

parser.add_argument(
    "--enable-workflow-routing",
    action="store_true",
    help="Enable workflow-aware routing (requires kvaware routing)"
)
```

### 6.2 Update Helm Values
File: `/helm/values.yaml`

```yaml
router:
  # ... existing config ...
  workflowRouting:
    enabled: false
    ttl: 3600
```

## Step 7: Documentation

### 7.1 Usage Example
```bash
# Start router with workflow-aware routing
python -m vllm_router \
    --routing-logic workflow_aware \
    --lmcache-controller-port 9000 \
    --session-key "x-user-id" \
    --workflow-ttl 3600

# Send requests with workflow context
curl -X POST http://localhost:30080/v1/completions \
  -H "Content-Type: application/json" \
  -H "X-Workflow-Id: my-workflow-123" \
  -H "X-Agent-Id: agent-1" \
  -d '{
    "model": "meta-llama/Llama-3.1-8B-Instruct",
    "prompt": "Analyze this data...",
    "max_tokens": 100,
    "workflow_id": "my-workflow-123",
    "agent_id": "agent-1"
  }'
```

## Next Steps

1. Implement the prototype
2. Add comprehensive tests
3. Benchmark performance improvements
4. Add observability metrics
5. Create migration guide for existing deployments