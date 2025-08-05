# RFC: Agent-Aware KV-Cache Management for vLLM

## Summary

This RFC proposes adding agent-aware KV-cache management capabilities to vLLM core, enabling native support for multi-agent workflows with improved cache efficiency and performance.

## Motivation

With the rise of multi-agent AI systems (LangChain, AutoGen, BeeAI, Anthropic MCP), there's a growing need for LLM serving engines to understand and optimize for agent-based workflows. Current vLLM treats each request independently, missing opportunities for:

1. **Context Reuse**: Agents in the same workflow often share context
2. **Intelligent Routing**: Requests from the same workflow should prefer the same instance
3. **Cache Efficiency**: Agent-specific eviction policies can improve hit rates
4. **Performance**: 3-10x latency reduction possible through smart caching

## Proposed Changes

### 1. Core Data Structure Changes

#### Add Agent Metadata to SequenceGroup

```python
# vllm/sequence.py

from dataclasses import dataclass
from typing import Optional, Dict, Any

@dataclass
class AgentMetadata:
    """Metadata for agent-aware request handling"""
    workflow_id: Optional[str] = None
    agent_id: Optional[str] = None
    parent_request_id: Optional[str] = None
    workflow_priority: float = 1.0
    shared_context_keys: List[str] = field(default_factory=list)
    
class SequenceGroup:
    """A group of sequences that are generated from the same prompt."""
    
    def __init__(
        self,
        request_id: str,
        seqs: List[Sequence],
        sampling_params: SamplingParams,
        arrival_time: float,
        agent_metadata: Optional[AgentMetadata] = None,  # NEW
    ) -> None:
        self.request_id = request_id
        self.seqs = seqs
        self.sampling_params = sampling_params
        self.arrival_time = arrival_time
        self.agent_metadata = agent_metadata or AgentMetadata()  # NEW
```

#### Extend SamplingParams

```python
# vllm/sampling_params.py

class SamplingParams:
    """Sampling parameters for text generation."""
    
    def __init__(
        self,
        # ... existing parameters ...
        workflow_id: Optional[str] = None,  # NEW
        agent_id: Optional[str] = None,  # NEW
        parent_request_id: Optional[str] = None,  # NEW
        cache_affinity: Optional[str] = None,  # NEW: preferred instance
    ) -> None:
        # ... existing initialization ...
        self.workflow_id = workflow_id
        self.agent_id = agent_id
        self.parent_request_id = parent_request_id
        self.cache_affinity = cache_affinity
```

### 2. Agent-Aware Block Management

#### Enhanced BlockSpaceManager

```python
# vllm/core/block_manager.py

class AgentAwareBlockSpaceManager(BlockSpaceManager):
    """Block manager with agent-aware allocation and eviction"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.workflow_blocks: Dict[str, Set[int]] = defaultdict(set)
        self.agent_access_patterns: Dict[str, List[float]] = defaultdict(list)
        self.workflow_priorities: Dict[str, float] = {}
        
    def allocate(self, seq_group: SequenceGroup) -> None:
        """Allocate blocks with workflow awareness"""
        super().allocate(seq_group)
        
        if seq_group.agent_metadata.workflow_id:
            # Track blocks used by workflow
            workflow_id = seq_group.agent_metadata.workflow_id
            for seq in seq_group.seqs:
                blocks = self.block_tables[seq.seq_id]
                self.workflow_blocks[workflow_id].update(blocks)
                
            # Update access pattern
            self.agent_access_patterns[workflow_id].append(time.time())
            
    def _get_eviction_candidates(self) -> List[int]:
        """Get blocks to evict with workflow-aware policy"""
        candidates = []
        
        # Group blocks by workflow
        workflow_block_groups = defaultdict(list)
        for block_id in self.gpu_allocator.free_blocks:
            workflow_id = self._get_block_workflow(block_id)
            workflow_block_groups[workflow_id].append(block_id)
            
        # Sort workflows by priority and recency
        sorted_workflows = sorted(
            workflow_block_groups.keys(),
            key=lambda w: (
                self.workflow_priorities.get(w, 1.0),
                self._get_workflow_recency(w)
            )
        )
        
        # Evict entire workflows to maintain coherency
        for workflow_id in sorted_workflows:
            candidates.extend(workflow_block_groups[workflow_id])
            if len(candidates) >= self.num_blocks_to_evict:
                break
                
        return candidates[:self.num_blocks_to_evict]
```

### 3. Agent-Aware Scheduling

#### Enhanced Scheduler

```python
# vllm/core/scheduler.py

class AgentAwareScheduler(Scheduler):
    """Scheduler with agent workflow understanding"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.workflow_queues: Dict[str, Deque[SequenceGroup]] = defaultdict(deque)
        self.workflow_batch_preference = 0.8  # Prefer batching same workflow
        
    def _schedule(self) -> SchedulerOutputs:
        """Schedule with workflow affinity"""
        scheduled: List[SequenceGroup] = []
        
        # First, try to schedule from same workflow
        if self.running:
            running_workflows = {
                sg.agent_metadata.workflow_id 
                for sg in self.running 
                if sg.agent_metadata.workflow_id
            }
            
            for workflow_id in running_workflows:
                if workflow_id in self.workflow_queues:
                    while self.workflow_queues[workflow_id]:
                        if self._can_schedule(self.workflow_queues[workflow_id][0]):
                            scheduled.append(
                                self.workflow_queues[workflow_id].popleft()
                            )
                        else:
                            break
                            
        # Then schedule other requests
        return self._schedule_remaining(scheduled)
```

### 4. Cache Sharing Protocol

#### Workflow Context Manager

```python
# vllm/core/workflow_context.py

class WorkflowContextManager:
    """Manages shared context across agents in a workflow"""
    
    def __init__(self):
        self.workflow_contexts: Dict[str, WorkflowContext] = {}
        self.context_cache: Dict[str, torch.Tensor] = {}
        
    def register_workflow(
        self, 
        workflow_id: str,
        expected_agents: Optional[List[str]] = None
    ) -> None:
        """Register a new workflow"""
        self.workflow_contexts[workflow_id] = WorkflowContext(
            workflow_id=workflow_id,
            expected_agents=expected_agents or [],
            created_at=time.time()
        )
        
    def share_kv_cache(
        self,
        workflow_id: str,
        agent_id: str,
        kv_cache: torch.Tensor,
        token_ids: List[int]
    ) -> None:
        """Share KV-cache within workflow"""
        cache_key = f"{workflow_id}:{hash(tuple(token_ids))}"
        self.context_cache[cache_key] = kv_cache.clone()
        
    def get_shared_cache(
        self,
        workflow_id: str,
        token_ids: List[int]
    ) -> Optional[torch.Tensor]:
        """Retrieve shared cache if available"""
        cache_key = f"{workflow_id}:{hash(tuple(token_ids))}"
        return self.context_cache.get(cache_key)
```

### 5. API Changes

#### OpenAI-Compatible API Extension

```python
# vllm/entrypoints/openai/protocol.py

class CompletionRequest(BaseModel):
    # ... existing fields ...
    workflow_id: Optional[str] = Field(default=None, 
        description="Workflow identifier for agent coordination")
    agent_id: Optional[str] = Field(default=None,
        description="Agent identifier within workflow")
    parent_request_id: Optional[str] = Field(default=None,
        description="Parent request for tracing")
    cache_affinity: Optional[str] = Field(default=None,
        description="Preferred instance for cache locality")

class ChatCompletionRequest(BaseModel):
    # ... existing fields ...
    workflow_id: Optional[str] = Field(default=None)
    agent_id: Optional[str] = Field(default=None)
    parent_request_id: Optional[str] = Field(default=None)
    cache_affinity: Optional[str] = Field(default=None)
```

### 6. Metrics and Monitoring

```python
# vllm/metrics.py

class AgentAwareMetrics:
    """Metrics for agent-aware serving"""
    
    def __init__(self):
        # Workflow-level metrics
        self.workflow_cache_hit_rate = Gauge(
            "vllm:workflow_cache_hit_rate",
            "Cache hit rate per workflow"
        )
        self.workflow_latency = Histogram(
            "vllm:workflow_latency_seconds", 
            "Latency per workflow"
        )
        self.agent_queue_length = Gauge(
            "vllm:agent_queue_length",
            "Queue length per agent"
        )
        
        # Cross-agent metrics
        self.context_reuse_rate = Gauge(
            "vllm:context_reuse_rate",
            "Rate of context reuse across agents"
        )
        self.workflow_batch_efficiency = Gauge(
            "vllm:workflow_batch_efficiency",
            "Efficiency of workflow-aware batching"
        )
```

## Implementation Plan

### Phase 1: Core Infrastructure (2-3 weeks)
1. Add agent metadata to core data structures
2. Implement workflow context manager
3. Add basic metrics

### Phase 2: Block Management (2-3 weeks)
1. Implement agent-aware block allocation
2. Add workflow-aware eviction policies
3. Test with synthetic workloads

### Phase 3: Scheduling (2-3 weeks)
1. Implement workflow-aware scheduling
2. Add batching preferences
3. Optimize for cache locality

### Phase 4: API and Integration (1-2 weeks)
1. Extend OpenAI API
2. Add configuration options
3. Create examples and documentation

### Phase 5: Production Hardening (2-3 weeks)
1. Performance benchmarking
2. Edge case handling
3. Production testing

## Benchmarking

### Test Scenarios

1. **Multi-Agent Chat**: Agents discussing a topic
2. **Pipeline Processing**: Sequential agent workflow
3. **Parallel Analysis**: Multiple agents analyzing data
4. **Mixed Workload**: Agent and non-agent requests

### Expected Results

- 3-10x latency reduction for multi-agent workflows
- 40-60% improvement in cache hit rate
- 25-40% reduction in memory usage through better sharing

## Configuration

```yaml
# Example configuration
agent_aware_serving:
  enabled: true
  workflow_ttl: 3600  # seconds
  max_workflows: 1000
  eviction_policy: "workflow_lru"  # or "agent_priority"
  batching_preference: 0.8  # 0-1, higher prefers same workflow
  cache_sharing:
    enabled: true
    max_shared_contexts: 10000
```

## Compatibility

- Fully backward compatible
- Opt-in via configuration
- No performance impact when disabled
- Works with existing vLLM features

## Future Extensions

1. **Distributed Workflows**: Cross-instance workflow coordination
2. **Workflow Templates**: Pre-defined workflow patterns
3. **Agent Marketplace**: Standard agent interfaces
4. **Federated Learning**: Learn from workflow patterns

## References

- Production-stack agent-aware routing implementation
- BeeAI framework patterns
- Anthropic MCP specification
- LangChain multi-agent patterns

## Conclusion

Agent-aware KV-cache management will position vLLM as the premier serving engine for the emerging multi-agent AI ecosystem, providing significant performance benefits while maintaining backward compatibility.