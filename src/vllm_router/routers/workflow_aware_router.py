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

"""Workflow-aware routing for multi-agent optimization."""

from typing import Dict, List, Optional
import logging

from vllm_router.routers.routing_logic import KvawareRouter, RoutingInterface
from vllm_router.service_discovery import EndpointInfo
from vllm_router.stats.engine_stats import EngineStats
from vllm_router.stats.request_stats import RequestStats
from vllm_router.services.workflow_service import WorkflowContextManager
from vllm_router.models.workflow import WorkflowMetadata
from vllm_router.log import init_logger
from fastapi import Request

logger = init_logger(__name__)


class WorkflowAwareRouter(KvawareRouter):
    """Router with workflow-aware capabilities for multi-agent optimization."""
    
    def __init__(
        self,
        lmcache_controller_port: int,
        session_key: str,
        kv_aware_threshold: int = 2000,
        workflow_ttl: int = 3600,
        max_workflows: int = 1000,
        batching_preference: float = 0.8
    ):
        """Initialize workflow-aware router.
        
        Args:
            lmcache_controller_port: Port for LMCache controller
            session_key: Session key for routing
            kv_aware_threshold: Threshold for KV-aware routing
            workflow_ttl: TTL for workflow contexts in seconds
            max_workflows: Maximum concurrent workflows
            batching_preference: Preference for batching same workflow (0.0-1.0)
        """
        super().__init__(lmcache_controller_port, session_key, kv_aware_threshold)
        
        self.workflow_manager = WorkflowContextManager(
            ttl=workflow_ttl,
            max_workflows=max_workflows
        )
        self.batching_preference = batching_preference
        
        # Metrics
        self.workflow_cache_hits = 0
        self.total_workflow_requests = 0
        self.workflow_routing_decisions = 0
        
    async def start(self):
        """Start router and workflow manager."""
        # Start parent KV manager
        super().start_kv_manager()
        
        # Start workflow manager
        await self.workflow_manager.start()
        logger.info("Started workflow-aware router")
        
    async def stop(self):
        """Stop router and workflow manager."""
        await self.workflow_manager.stop()
        logger.info("Stopped workflow-aware router")
        
    async def route_request(
        self,
        endpoints: List[EndpointInfo],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
        request: Request,
        request_json: Dict,
    ) -> str:
        """Route request with workflow awareness.
        
        This method extends KV-aware routing with workflow affinity to optimize
        multi-agent workflows through better cache utilization.
        
        Args:
            endpoints: Available backend endpoints
            engine_stats: Engine statistics
            request_stats: Request statistics
            request: FastAPI request object
            request_json: Parsed request JSON
            
        Returns:
            Selected backend URL
        """
        # Extract workflow metadata
        workflow_metadata = None
        workflow_id = None
        agent_id = None
        
        # Check for workflow metadata in request
        if "workflow_metadata" in request_json:
            workflow_data = request_json["workflow_metadata"]
            workflow_metadata = WorkflowMetadata(**workflow_data)
            workflow_id = workflow_metadata.workflow_id
            agent_id = workflow_metadata.agent_id
        
        # If no workflow metadata, fall back to parent routing
        if not workflow_id:
            return await super().route_request(
                endpoints, engine_stats, request_stats, request, request_json
            )
            
        # Increment workflow request counter
        self.total_workflow_requests += 1
        self.workflow_routing_decisions += 1
        
        # Register workflow if new
        workflow_context = await self.workflow_manager.get_workflow(workflow_id)
        if not workflow_context:
            workflow_context = await self.workflow_manager.register_workflow(
                workflow_id, workflow_metadata
            )
            
        # Register agent if provided
        if agent_id:
            await self.workflow_manager.register_agent(workflow_id, agent_id)
            
        # Get current instance loads
        instance_loads = self._calculate_instance_loads(
            endpoints, engine_stats, request_stats
        )
        
        # Get instance assignment with workflow affinity
        available_urls = [e.url for e in endpoints]
        assigned_instance = await self.workflow_manager.assign_instance(
            workflow_id, agent_id, available_urls, instance_loads
        )
        
        # Check if we can benefit from KV cache
        cache_benefit = await self._check_cache_benefit(
            workflow_id, request_json, assigned_instance
        )
        if cache_benefit:
            self.workflow_cache_hits += 1
            
        # Update workflow stats
        await self.workflow_manager.update_workflow_stats(
            workflow_id, cache_hit=cache_benefit, tokens=0
        )
        
        logger.info(
            f"Routing workflow {workflow_id} agent {agent_id} to {assigned_instance} "
            f"(cache_benefit={cache_benefit})"
        )
        
        return assigned_instance
        
    def _calculate_instance_loads(
        self,
        endpoints: List[EndpointInfo],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats]
    ) -> Dict[str, float]:
        """Calculate normalized load for each instance.
        
        Returns:
            Dict mapping instance URL to load (0.0-1.0)
        """
        loads = {}
        
        for endpoint in endpoints:
            url = endpoint.url
            load = 0.0
            
            # Factor in engine stats if available
            if url in engine_stats:
                stats = engine_stats[url]
                # Normalize GPU utilization
                if hasattr(stats, 'gpu_utilization'):
                    load += stats.gpu_utilization * 0.4
                # Normalize memory usage
                if hasattr(stats, 'memory_usage_fraction'):
                    load += stats.memory_usage_fraction * 0.3
                    
            # Factor in request stats if available
            if url in request_stats:
                stats = request_stats[url]
                # Normalize QPS (assume max 100 QPS)
                if hasattr(stats, 'qps'):
                    load += min(stats.qps / 100.0, 1.0) * 0.3
                    
            loads[url] = min(load, 1.0)  # Cap at 1.0
            
        return loads
        
    async def _check_cache_benefit(
        self,
        workflow_id: str,
        request_json: Dict,
        instance_url: str
    ) -> bool:
        """Check if this request can benefit from KV cache.
        
        This is a simplified check - in practice would query actual cache state.
        
        Args:
            workflow_id: Workflow ID
            request_json: Request data
            instance_url: Assigned instance
            
        Returns:
            True if cache benefit expected
        """
        # Check if this workflow has previous requests
        workflow_context = await self.workflow_manager.get_workflow(workflow_id)
        if not workflow_context or workflow_context.total_requests == 0:
            return False
            
        # Check if prompt has significant overlap (simplified)
        # In practice, would check actual KV cache state
        prompt = request_json.get("prompt", "")
        if len(prompt) > self.kv_aware_threshold:
            return True
            
        return False
        
    async def get_workflow_stats(self) -> Dict[str, Any]:
        """Get workflow routing statistics."""
        manager_stats = await self.workflow_manager.get_workflow_stats()
        
        cache_hit_rate = 0.0
        if self.total_workflow_requests > 0:
            cache_hit_rate = self.workflow_cache_hits / self.total_workflow_requests
            
        return {
            "workflow_routing": {
                "total_requests": self.total_workflow_requests,
                "cache_hits": self.workflow_cache_hits,
                "cache_hit_rate": cache_hit_rate,
                "routing_decisions": self.workflow_routing_decisions
            },
            "workflow_manager": manager_stats
        }