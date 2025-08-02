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

"""Workflow context management for multi-agent coordination."""

import asyncio
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict
import time
import logging

from vllm_router.models.workflow import WorkflowContext, WorkflowMetadata
from vllm_router.log import init_logger

logger = init_logger(__name__)


class WorkflowContextManager:
    """Manages workflow contexts and agent coordination."""
    
    def __init__(
        self, 
        ttl: int = 3600,
        max_workflows: int = 1000,
        cleanup_interval: int = 60
    ):
        """Initialize workflow context manager.
        
        Args:
            ttl: Time-to-live for workflows in seconds
            max_workflows: Maximum number of concurrent workflows
            cleanup_interval: Interval for cleanup task in seconds
        """
        self.workflows: Dict[str, WorkflowContext] = {}
        self.workflow_instances: Dict[str, str] = {}  # workflow_id -> instance_url
        self.agent_instances: Dict[Tuple[str, str], str] = {}  # (workflow_id, agent_id) -> instance_url
        self.instance_workflows: Dict[str, Set[str]] = defaultdict(set)  # instance_url -> set of workflow_ids
        
        self.workflow_ttl = ttl
        self.max_workflows = max_workflows
        self.cleanup_interval = cleanup_interval
        self._cleanup_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        
        # Metrics
        self.total_workflows_created = 0
        self.total_workflows_expired = 0
        
    async def start(self):
        """Start background cleanup task."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("Started workflow cleanup task")
            
    async def stop(self):
        """Stop background cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            logger.info("Stopped workflow cleanup task")
            
    async def _cleanup_loop(self):
        """Background task to clean up expired workflows."""
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval)
                await self._cleanup_expired_workflows()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
                
    async def _cleanup_expired_workflows(self):
        """Remove expired workflows."""
        async with self._lock:
            expired_workflows = []
            
            for workflow_id, context in self.workflows.items():
                if not context.is_active(self.workflow_ttl):
                    expired_workflows.append(workflow_id)
                    
            for workflow_id in expired_workflows:
                await self._remove_workflow(workflow_id)
                self.total_workflows_expired += 1
                
            if expired_workflows:
                logger.info(f"Cleaned up {len(expired_workflows)} expired workflows")
                
    async def _remove_workflow(self, workflow_id: str):
        """Remove a workflow and its associated data."""
        # Remove workflow context
        if workflow_id in self.workflows:
            del self.workflows[workflow_id]
            
        # Remove instance mapping
        if workflow_id in self.workflow_instances:
            instance_url = self.workflow_instances[workflow_id]
            del self.workflow_instances[workflow_id]
            
            # Remove from instance's workflow set
            if instance_url in self.instance_workflows:
                self.instance_workflows[instance_url].discard(workflow_id)
                if not self.instance_workflows[instance_url]:
                    del self.instance_workflows[instance_url]
                    
        # Remove agent mappings
        agent_keys_to_remove = [
            key for key in self.agent_instances.keys() 
            if key[0] == workflow_id
        ]
        for key in agent_keys_to_remove:
            del self.agent_instances[key]
            
    async def register_workflow(
        self, 
        workflow_id: str, 
        metadata: WorkflowMetadata
    ) -> WorkflowContext:
        """Register a new workflow.
        
        Args:
            workflow_id: Unique workflow identifier
            metadata: Workflow metadata
            
        Returns:
            WorkflowContext object
            
        Raises:
            ValueError: If max workflows exceeded
        """
        async with self._lock:
            # Check if workflow already exists
            if workflow_id in self.workflows:
                return self.workflows[workflow_id]
                
            # Check max workflows limit
            if len(self.workflows) >= self.max_workflows:
                # Try cleanup first
                await self._cleanup_expired_workflows()
                
                if len(self.workflows) >= self.max_workflows:
                    raise ValueError(f"Maximum workflows ({self.max_workflows}) exceeded")
                    
            # Create new workflow context
            context = WorkflowContext(
                workflow_id=workflow_id,
                metadata=metadata
            )
            
            self.workflows[workflow_id] = context
            self.total_workflows_created += 1
            
            logger.info(f"Registered workflow {workflow_id}")
            return context
            
    async def get_workflow(self, workflow_id: str) -> Optional[WorkflowContext]:
        """Get workflow context by ID."""
        async with self._lock:
            return self.workflows.get(workflow_id)
            
    async def assign_instance(
        self, 
        workflow_id: str, 
        agent_id: Optional[str],
        available_instances: List[str],
        current_loads: Optional[Dict[str, float]] = None
    ) -> str:
        """Assign instance with workflow affinity.
        
        Args:
            workflow_id: Workflow ID
            agent_id: Agent ID (optional)
            available_instances: List of available instance URLs
            current_loads: Optional dict of instance URL to load (0.0-1.0)
            
        Returns:
            Assigned instance URL
        """
        async with self._lock:
            # Check if workflow already assigned
            if workflow_id in self.workflow_instances:
                assigned = self.workflow_instances[workflow_id]
                # Verify instance is still available
                if assigned in available_instances:
                    return assigned
                    
            # Check for agent-specific assignment
            if agent_id and (workflow_id, agent_id) in self.agent_instances:
                assigned = self.agent_instances[(workflow_id, agent_id)]
                if assigned in available_instances:
                    return assigned
                    
            # Find best instance based on load and existing workflows
            best_instance = await self._find_best_instance(
                workflow_id, available_instances, current_loads
            )
            
            # Store assignment
            self.workflow_instances[workflow_id] = best_instance
            if agent_id:
                self.agent_instances[(workflow_id, agent_id)] = best_instance
                
            # Track instance workflows
            self.instance_workflows[best_instance].add(workflow_id)
            
            # Update workflow context
            if workflow_id in self.workflows:
                self.workflows[workflow_id].assigned_instance = best_instance
                
            logger.debug(f"Assigned workflow {workflow_id} to instance {best_instance}")
            return best_instance
            
    async def _find_best_instance(
        self,
        workflow_id: str,
        available_instances: List[str],
        current_loads: Optional[Dict[str, float]] = None
    ) -> str:
        """Find the best instance for a workflow.
        
        Selection criteria:
        1. Instance with fewest workflows
        2. Instance with lowest load (if provided)
        3. Random selection as tiebreaker
        """
        if not available_instances:
            raise ValueError("No available instances")
            
        # If only one instance, return it
        if len(available_instances) == 1:
            return available_instances[0]
            
        # Calculate scores for each instance
        instance_scores = {}
        
        for instance in available_instances:
            # Base score from workflow count (lower is better)
            workflow_count = len(self.instance_workflows.get(instance, set()))
            score = workflow_count
            
            # Adjust for load if provided
            if current_loads and instance in current_loads:
                load = current_loads[instance]
                score += load * 10  # Weight load heavily
                
            instance_scores[instance] = score
            
        # Select instance with lowest score
        best_instance = min(instance_scores, key=instance_scores.get)
        return best_instance
        
    async def update_workflow_stats(
        self,
        workflow_id: str,
        cache_hit: bool = False,
        tokens: int = 0
    ):
        """Update workflow statistics."""
        async with self._lock:
            if workflow_id in self.workflows:
                self.workflows[workflow_id].update_stats(cache_hit, tokens)
                
    async def register_agent(self, workflow_id: str, agent_id: str):
        """Register an agent in a workflow."""
        async with self._lock:
            if workflow_id in self.workflows:
                self.workflows[workflow_id].register_agent(agent_id)
                
    async def get_workflow_stats(self) -> Dict[str, Any]:
        """Get overall workflow statistics."""
        async with self._lock:
            active_workflows = sum(
                1 for w in self.workflows.values() 
                if w.is_active(self.workflow_ttl)
            )
            
            total_agents = sum(
                len(w.active_agents) 
                for w in self.workflows.values()
            )
            
            avg_cache_hit_rate = 0.0
            if self.workflows:
                rates = [w.get_cache_hit_rate() for w in self.workflows.values()]
                avg_cache_hit_rate = sum(rates) / len(rates)
                
            return {
                "total_workflows_created": self.total_workflows_created,
                "total_workflows_expired": self.total_workflows_expired,
                "active_workflows": active_workflows,
                "total_agents": total_agents,
                "avg_cache_hit_rate": avg_cache_hit_rate,
                "instance_distribution": {
                    instance: len(workflows)
                    for instance, workflows in self.instance_workflows.items()
                }
            }