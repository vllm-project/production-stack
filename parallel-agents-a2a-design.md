# Parallel Agents and A2A Communication Design

## Overview
This document extends the workflow-aware routing design to support parallel agent execution and agent-to-agent (A2A) communication in vLLM production-stack.

## Architecture Overview

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Agent A   │────▶│   Agent B   │────▶│   Agent C   │  Sequential
└─────────────┘     └─────────────┘     └─────────────┘

┌─────────────┐
│   Agent A   │──┐
└─────────────┘  │   ┌─────────────┐
                 ├──▶│ Coordinator │     Parallel with A2A
┌─────────────┐  │   └─────────────┘
│   Agent B   │──┤         ▲
└─────────────┘  │         │
                 │         ▼
┌─────────────┐  │   ┌─────────────┐
│   Agent C   │──┴──▶│ Shared State│
└─────────────┘      └─────────────┘
```

## Core Components

### 1. Workflow Execution Modes

```python
class WorkflowExecutionMode(enum.Enum):
    SEQUENTIAL = "sequential"      # Agents execute one after another
    PARALLEL = "parallel"          # Agents execute simultaneously
    HYBRID = "hybrid"             # Mix of sequential and parallel
    DAG = "dag"                   # Directed Acyclic Graph execution
```

### 2. Agent Communication Protocol

```python
@dataclass
class AgentMessage:
    """Message structure for A2A communication"""
    workflow_id: str
    source_agent_id: str
    target_agent_id: str
    message_type: str  # "data", "signal", "query", "response"
    payload: Dict[str, Any]
    timestamp: float
    sequence_num: int
    parent_message_id: Optional[str] = None
```

### 3. Workflow Context Manager

```python
class WorkflowContextManager:
    """Manages shared context and A2A communication for workflows"""
    
    def __init__(self):
        self.workflow_contexts: Dict[str, WorkflowContext] = {}
        self.agent_mailboxes: Dict[Tuple[str, str], List[AgentMessage]] = {}
        self.workflow_barriers: Dict[str, asyncio.Barrier] = {}
        
    async def register_agent(self, workflow_id: str, agent_id: str):
        """Register an agent in a workflow"""
        
    async def send_message(self, message: AgentMessage):
        """Send message from one agent to another"""
        
    async def receive_messages(self, workflow_id: str, agent_id: str) -> List[AgentMessage]:
        """Receive pending messages for an agent"""
        
    async def wait_for_agents(self, workflow_id: str, agent_ids: List[str]):
        """Synchronization barrier for parallel agents"""
```

## Implementation Details

### 1. Extended Workflow-Aware Router

```python
class ParallelWorkflowRouter(WorkflowAwareRouter):
    """
    Extends WorkflowAwareRouter to support parallel agent execution
    and A2A communication
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.context_manager = WorkflowContextManager()
        self.workflow_execution_modes: Dict[str, WorkflowExecutionMode] = {}
        self.agent_dependencies: Dict[str, Dict[str, List[str]]] = {}
        
    async def route_request(
        self,
        endpoints,
        engine_stats,
        request_stats,
        request,
        request_json,
        workflow_context: Optional[Dict] = None
    ):
        """Route with parallel execution awareness"""
        
        workflow_id = workflow_context.get("workflow_id") if workflow_context else None
        agent_id = workflow_context.get("agent_id") if workflow_context else None
        execution_mode = workflow_context.get("execution_mode", "sequential")
        
        if workflow_id and agent_id:
            # Register agent
            await self.context_manager.register_agent(workflow_id, agent_id)
            
            # Check for A2A messages
            messages = await self.context_manager.receive_messages(workflow_id, agent_id)
            if messages:
                # Inject messages into request context
                request_json["agent_messages"] = [msg.payload for msg in messages]
        
        # For parallel execution, consider load distribution
        if execution_mode in ["parallel", "hybrid"]:
            return await self._route_parallel_agent(
                endpoints, engine_stats, workflow_id, agent_id
            )
        else:
            return await super().route_request(
                endpoints, engine_stats, request_stats, request, request_json, workflow_context
            )
    
    async def _route_parallel_agent(
        self,
        endpoints,
        engine_stats,
        workflow_id: str,
        agent_id: str
    ) -> str:
        """Route parallel agents to distribute load"""
        
        # Get current workflow load distribution
        workflow_loads = self._calculate_workflow_loads(endpoints)
        
        # Find instance with lowest load for this workflow
        best_instance = None
        min_load = float('inf')
        
        for endpoint in endpoints:
            url = endpoint.url
            load = workflow_loads.get(url, 0)
            
            # Prefer instances already handling this workflow (for cache)
            if workflow_id in self.instance_workflows.get(url, set()):
                load *= 0.7  # 30% preference for cache locality
                
            if load < min_load:
                min_load = load
                best_instance = url
                
        return best_instance
```

### 2. A2A Communication API

```python
# New endpoint for A2A communication
@router.post("/v1/workflows/{workflow_id}/messages")
async def send_agent_message(
    workflow_id: str,
    message: AgentMessage,
    background_tasks: BackgroundTasks
):
    """Send message between agents"""
    
    # Validate workflow and agents exist
    if not validate_workflow_agent(workflow_id, message.source_agent_id):
        raise HTTPException(status_code=404, detail="Invalid workflow or agent")
    
    # Store message
    await app.state.context_manager.send_message(message)
    
    # Optional: trigger target agent if waiting
    background_tasks.add_task(
        notify_agent, workflow_id, message.target_agent_id
    )
    
    return {"status": "sent", "message_id": message.message_id}

@router.get("/v1/workflows/{workflow_id}/agents/{agent_id}/messages")
async def get_agent_messages(
    workflow_id: str,
    agent_id: str,
    since: Optional[float] = None
):
    """Retrieve messages for an agent"""
    
    messages = await app.state.context_manager.receive_messages(
        workflow_id, agent_id, since=since
    )
    
    return {
        "messages": [msg.dict() for msg in messages],
        "count": len(messages)
    }
```

### 3. Workflow Definition Schema

```python
@dataclass
class WorkflowDefinition:
    """Define workflow structure and agent relationships"""
    workflow_id: str
    execution_mode: WorkflowExecutionMode
    agents: List[AgentDefinition]
    dependencies: Dict[str, List[str]]  # agent_id -> [dependent_agent_ids]
    shared_context: Dict[str, Any]
    timeout: Optional[int] = 3600

@dataclass
class AgentDefinition:
    agent_id: str
    agent_type: str
    model: str
    max_parallel: int = 1  # Max parallel instances
    retry_policy: Optional[Dict] = None
    input_schema: Optional[Dict] = None
    output_schema: Optional[Dict] = None
```

### 4. Synchronization Primitives

```python
class WorkflowSynchronizer:
    """Synchronization primitives for parallel agents"""
    
    async def barrier(self, workflow_id: str, agent_ids: List[str]):
        """Wait for all specified agents to reach this point"""
        
    async def mutex_acquire(self, workflow_id: str, resource_id: str, agent_id: str):
        """Acquire exclusive access to a shared resource"""
        
    async def mutex_release(self, workflow_id: str, resource_id: str, agent_id: str):
        """Release exclusive access"""
        
    async def semaphore_acquire(self, workflow_id: str, resource_id: str, limit: int):
        """Acquire one of N available resources"""
```

## Use Cases

### 1. Parallel Data Processing
```python
# Workflow definition
workflow = {
    "workflow_id": "data-analysis-001",
    "execution_mode": "parallel",
    "agents": [
        {"agent_id": "analyzer-1", "type": "data-analyzer"},
        {"agent_id": "analyzer-2", "type": "data-analyzer"},
        {"agent_id": "analyzer-3", "type": "data-analyzer"},
        {"agent_id": "aggregator", "type": "result-aggregator"}
    ],
    "dependencies": {
        "aggregator": ["analyzer-1", "analyzer-2", "analyzer-3"]
    }
}
```

### 2. Multi-Agent Reasoning
```python
# Agents communicate to reach consensus
workflow = {
    "workflow_id": "consensus-001",
    "execution_mode": "hybrid",
    "agents": [
        {"agent_id": "proposer", "type": "proposal-generator"},
        {"agent_id": "critic-1", "type": "critic"},
        {"agent_id": "critic-2", "type": "critic"},
        {"agent_id": "synthesizer", "type": "synthesis"}
    ],
    "communication_pattern": "all-to-all"
}
```

### 3. Pipeline with Feedback
```python
# Agents can send feedback to previous stages
workflow = {
    "workflow_id": "iterative-001",
    "execution_mode": "dag",
    "agents": [
        {"agent_id": "generator", "type": "content-generator"},
        {"agent_id": "validator", "type": "quality-validator"},
        {"agent_id": "refiner", "type": "content-refiner"}
    ],
    "edges": [
        {"from": "generator", "to": "validator"},
        {"from": "validator", "to": "refiner", "condition": "needs_refinement"},
        {"from": "refiner", "to": "generator", "type": "feedback"}
    ]
}
```

## Performance Optimizations

### 1. Context Sharing Strategy
```python
class ContextSharingStrategy(enum.Enum):
    BROADCAST = "broadcast"        # All agents get full context
    SELECTIVE = "selective"        # Agents get relevant context only
    LAZY = "lazy"                 # Context loaded on demand
    HIERARCHICAL = "hierarchical" # Context organized in levels
```

### 2. Load Balancing for Parallel Agents
```python
def calculate_optimal_distribution(
    workflow: WorkflowDefinition,
    available_instances: List[EndpointInfo]
) -> Dict[str, str]:
    """Calculate optimal agent-to-instance mapping"""
    
    # Consider:
    # - Current instance loads
    # - KV-cache locality
    # - Network topology
    # - Agent communication patterns
    
    return distribution_map
```

### 3. Message Batching
```python
class MessageBatcher:
    """Batch A2A messages for efficiency"""
    
    def __init__(self, batch_size: int = 10, batch_timeout: float = 0.1):
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.pending_messages: Dict[str, List[AgentMessage]] = {}
```

## Monitoring and Observability

### 1. Workflow Metrics
```python
@dataclass
class WorkflowMetrics:
    workflow_id: str
    start_time: float
    end_time: Optional[float]
    total_agents: int
    completed_agents: int
    failed_agents: int
    total_messages: int
    avg_message_latency: float
    total_tokens: int
    cache_hit_rate: float
    parallel_efficiency: float  # Speedup vs sequential
```

### 2. A2A Communication Metrics
```python
@dataclass
class A2AMetrics:
    message_count: int
    avg_message_size: float
    avg_delivery_latency: float
    message_types: Dict[str, int]
    agent_pairs: Dict[Tuple[str, str], int]
```

## Testing Strategy

### 1. Unit Tests
- Test parallel routing logic
- Test A2A message delivery
- Test synchronization primitives

### 2. Integration Tests
- Test full parallel workflow execution
- Test agent communication patterns
- Test failure recovery

### 3. Performance Tests
- Benchmark parallel vs sequential execution
- Measure A2A communication overhead
- Test scalability with many agents

## Migration Path

1. **Phase 1**: Basic parallel execution support
2. **Phase 2**: A2A message passing
3. **Phase 3**: Advanced synchronization
4. **Phase 4**: DAG workflow support
5. **Phase 5**: Full production deployment

## Configuration Example

```yaml
router:
  workflowRouting:
    enabled: true
    ttl: 3600
    parallelExecution:
      enabled: true
      maxParallelAgents: 10
    a2aCommunication:
      enabled: true
      messageTTL: 300
      maxMessageSize: 1MB
      batching:
        enabled: true
        batchSize: 10
        batchTimeout: 100ms
```