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

"""Workflow models for multi-agent support."""

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
import time
import uuid


class WorkflowMetadata(BaseModel):
    """Metadata for multi-agent workflows."""
    
    workflow_id: Optional[str] = Field(
        None, 
        description="Unique workflow identifier"
    )
    agent_id: Optional[str] = Field(
        None, 
        description="Agent identifier within workflow"
    )
    parent_request_id: Optional[str] = Field(
        None, 
        description="Parent request ID for tracing"
    )
    workflow_priority: float = Field(
        1.0, 
        description="Workflow priority for scheduling",
        ge=0.0,
        le=10.0
    )
    context_sharing_strategy: str = Field(
        "auto", 
        description="Context sharing strategy: auto|broadcast|selective|none"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, 
        description="Additional metadata"
    )
    
    class Config:
        extra = "allow"


class WorkflowContext(BaseModel):
    """Runtime context for an active workflow."""
    
    workflow_id: str
    created_at: float = Field(default_factory=time.time)
    last_updated: float = Field(default_factory=time.time)
    active_agents: Dict[str, float] = Field(
        default_factory=dict,
        description="Map of agent_id to last access time"
    )
    total_requests: int = 0
    cache_hits: int = 0
    total_tokens: int = 0
    assigned_instance: Optional[str] = None
    metadata: WorkflowMetadata = Field(default_factory=WorkflowMetadata)
    
    def register_agent(self, agent_id: str) -> None:
        """Register an agent as active in this workflow."""
        self.active_agents[agent_id] = time.time()
        self.last_updated = time.time()
    
    def update_stats(self, cache_hit: bool = False, tokens: int = 0) -> None:
        """Update workflow statistics."""
        self.total_requests += 1
        if cache_hit:
            self.cache_hits += 1
        self.total_tokens += tokens
        self.last_updated = time.time()
    
    def get_cache_hit_rate(self) -> float:
        """Calculate cache hit rate for this workflow."""
        if self.total_requests == 0:
            return 0.0
        return self.cache_hits / self.total_requests
    
    def is_active(self, ttl: int = 3600) -> bool:
        """Check if workflow is still active based on TTL."""
        return (time.time() - self.last_updated) < ttl


class AgentMessage(BaseModel):
    """Message for agent-to-agent communication."""
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id: str
    source_agent: str
    target_agent: str
    message_type: str = Field(
        "data",
        description="Message type: data|signal|query|response"
    )
    payload: Dict[str, Any]
    timestamp: float = Field(default_factory=time.time)
    ttl: int = Field(
        300,
        description="Message TTL in seconds"
    )
    
    def is_expired(self) -> bool:
        """Check if message has expired."""
        return (time.time() - self.timestamp) > self.ttl
    
    class Config:
        extra = "allow"