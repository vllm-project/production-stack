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
from typing import Dict, List, Optional, Set, Tuple, Any
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
        self._workflows: Dict[str, WorkflowContext] = {}
        self._workflow_instances: Dict[str, str] = {}  # workflow_id -> instance_url
        self._agent_instances: Dict[Tuple[str, str], str] = {}  # (workflow_id, agent_id) -> instance_url
        self._instance_workflows: Dict[str, Set[str]] = defaultdict(set)  # instance_url -> set of workflow_ids
        
        self.workflow_ttl = ttl
        self.max_workflows = max_workflows
        self.cleanup_interval = cleanup_interval
        self._cleanup_task: Optional[asyncio.Task] = None
        
        # Fine-grained locks to prevent race conditions
        self._workflow_lock = asyncio.Lock()  # For workflow registration/removal
        self._instance_lock = asyncio.Lock()  # For instance assignment
        self._stats_lock = asyncio.Lock()  # For statistics updates
        
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
        """Remove expired workflows with atomic operations."""
        # First, identify expired workflows without holding locks
        expired_workflows = []
        
        async with self._workflow_lock:
            for workflow_id, context in list(self._workflows.items()):
                if not context.is_active(self.workflow_ttl):
                    expired_workflows.append(workflow_id)
                    
        # Remove workflows one by one to minimize lock contention
        removed_count = 0
        for workflow_id in expired_workflows:
            try:
                await self._remove_workflow(workflow_id)
                removed_count += 1
            except Exception as e:
                logger.error(f"Error removing workflow {workflow_id}: {e}")
                
        if removed_count > 0:
            self.total_workflows_expired += removed_count
            logger.info(f"Cleaned up {removed_count} expired workflows")
                
    async def _remove_workflow(self, workflow_id: str):
        """Remove a workflow and its associated data atomically."""
        # Use separate locks to prevent deadlocks
        async with self._workflow_lock:
            # Remove workflow context
            if workflow_id in self._workflows:
                del self._workflows[workflow_id]
                
        async with self._instance_lock:
            # Remove instance mapping
            instance_url = None
            if workflow_id in self._workflow_instances:
                instance_url = self._workflow_instances[workflow_id]
                del self._workflow_instances[workflow_id]
                
            # Remove from instance's workflow set
            if instance_url and instance_url in self._instance_workflows:
                self._instance_workflows[instance_url].discard(workflow_id)
                if not self._instance_workflows[instance_url]:
                    del self._instance_workflows[instance_url]
                    
            # Remove agent mappings
            agent_keys_to_remove = [
                key for key in self._agent_instances.keys() 
                if key[0] == workflow_id
            ]
            for key in agent_keys_to_remove:
                del self._agent_instances[key]
            
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
        async with self._workflow_lock:
            # Check if workflow already exists
            if workflow_id in self._workflows:
                return self._workflows[workflow_id]
                
            # Check max workflows limit
            if len(self._workflows) >= self.max_workflows:
                # Try cleanup first (release lock during cleanup)
                pass  # Will cleanup outside lock
                
        # Cleanup outside lock to prevent deadlock
        if len(self._workflows) >= self.max_workflows:
            await self._cleanup_expired_workflows()
            
        async with self._workflow_lock:
            # Double-check after cleanup
            if workflow_id in self._workflows:
                return self._workflows[workflow_id]
                
            if len(self._workflows) >= self.max_workflows:
                raise ValueError(f"Maximum workflows ({self.max_workflows}) exceeded")
                
            # Create new workflow context
            context = WorkflowContext(
                workflow_id=workflow_id,
                metadata=metadata
            )
            
            self._workflows[workflow_id] = context
            self.total_workflows_created += 1
            
            logger.info(f"Registered workflow {workflow_id}")
            return context
            
    async def get_workflow(self, workflow_id: str) -> Optional[WorkflowContext]:
        """Get workflow context by ID."""
        async with self._workflow_lock:
            return self._workflows.get(workflow_id)
            
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
        async with self._instance_lock:
            # Check if workflow already assigned
            if workflow_id in self._workflow_instances:
                assigned = self._workflow_instances[workflow_id]
                # Verify instance is still available
                if assigned in available_instances:
                    return assigned
                    
            # Check for agent-specific assignment
            if agent_id and (workflow_id, agent_id) in self._agent_instances:
                assigned = self._agent_instances[(workflow_id, agent_id)]
                if assigned in available_instances:
                    return assigned
                    
            # Find best instance based on load and existing workflows
            best_instance = await self._find_best_instance(
                workflow_id, available_instances, current_loads
            )
            
            # Store assignment atomically
            self._workflow_instances[workflow_id] = best_instance
            if agent_id:
                self._agent_instances[(workflow_id, agent_id)] = best_instance
                
            # Track instance workflows
            self._instance_workflows[best_instance].add(workflow_id)
            
        # Update workflow context outside instance lock
        async with self._workflow_lock:
            if workflow_id in self._workflows:
                self._workflows[workflow_id].assigned_instance = best_instance
                
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
            
        # Calculate scores for each instance (called within lock)
        instance_scores = {}
        
        for instance in available_instances:
            # Base score from workflow count (lower is better)
            workflow_count = len(self._instance_workflows.get(instance, set()))
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
        async with self._stats_lock:
            async with self._workflow_lock:
                if workflow_id in self._workflows:
                    self._workflows[workflow_id].update_stats(cache_hit, tokens)
                
    async def register_agent(self, workflow_id: str, agent_id: str):
        """Register an agent in a workflow."""
        async with self._workflow_lock:
            if workflow_id in self._workflows:
                self._workflows[workflow_id].register_agent(agent_id)
                
    async def get_workflow_stats(self) -> Dict[str, Any]:
        """Get overall workflow statistics."""
        async with self._stats_lock:
            async with self._workflow_lock:
                active_workflows = sum(
                    1 for w in self._workflows.values() 
                    if w.is_active(self.workflow_ttl)
                )
                
                total_agents = sum(
                    len(w.active_agents) 
                    for w in self._workflows.values()
                )
                
                avg_cache_hit_rate = 0.0
                if self._workflows:
                    rates = [w.get_cache_hit_rate() for w in self._workflows.values()]
                    avg_cache_hit_rate = sum(rates) / len(rates)
                    
            async with self._instance_lock:
                instance_distribution = {
                    instance: len(workflows)
                    for instance, workflows in self._instance_workflows.items()
                }
                
            return {
                "total_workflows_created": self.total_workflows_created,
                "total_workflows_expired": self.total_workflows_expired,
                "active_workflows": active_workflows,
                "total_agents": total_agents,
                "avg_cache_hit_rate": avg_cache_hit_rate,
                "instance_distribution": instance_distribution
            }