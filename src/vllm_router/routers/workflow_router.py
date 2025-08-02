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

"""Workflow API endpoints for multi-agent coordination."""

from fastapi import APIRouter, HTTPException, Request
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from vllm_router.models.workflow import AgentMessage
from vllm_router.log import init_logger

logger = init_logger(__name__)

router = APIRouter(prefix="/v1/workflows", tags=["workflows"])


class SendMessageRequest(BaseModel):
    """Request model for sending agent messages."""
    source_agent: str = Field(..., description="Source agent ID")
    target_agent: str = Field(..., description="Target agent ID")
    message_type: str = Field("data", description="Message type: data|signal|query|response")
    payload: Dict[str, Any] = Field(..., description="Message payload")
    ttl: int = Field(300, description="Message TTL in seconds")


class MessageResponse(BaseModel):
    """Response model for message operations."""
    message_id: str
    status: str
    timestamp: float


class MessagesListResponse(BaseModel):
    """Response model for listing messages."""
    messages: List[Dict[str, Any]]
    count: int
    has_more: bool = False


class WorkflowStatusResponse(BaseModel):
    """Response model for workflow status."""
    workflow_id: str
    created_at: float
    last_updated: float
    active_agents: int
    total_requests: int
    cache_hits: int
    cache_hit_rate: float
    assigned_instance: Optional[str] = None


@router.post("/{workflow_id}/messages", response_model=MessageResponse)
async def send_agent_message(
    workflow_id: str,
    request: SendMessageRequest,
    app_request: Request
):
    """Send a message between agents in a workflow.
    
    This endpoint allows agents within a workflow to communicate by sending
    messages to each other. Messages are queued and can be retrieved by the
    target agent.
    
    Args:
        workflow_id: The workflow identifier
        request: Message details including source, target, and payload
        app_request: FastAPI request object for accessing app state
        
    Returns:
        MessageResponse with message ID and status
        
    Raises:
        HTTPException: If message queue is not available or message fails to send
    """
    # Get message queue from app state
    if not hasattr(app_request.app.state, 'message_queue'):
        raise HTTPException(
            status_code=503,
            detail="Message queue service not available"
        )
        
    message_queue = app_request.app.state.message_queue
    
    # Create agent message
    message = AgentMessage(
        workflow_id=workflow_id,
        source_agent=request.source_agent,
        target_agent=request.target_agent,
        message_type=request.message_type,
        payload=request.payload,
        ttl=request.ttl
    )
    
    # Send message
    success = await message_queue.send_message(message)
    
    if not success:
        raise HTTPException(
            status_code=503,
            detail="Failed to send message - queue may be full"
        )
        
    logger.info(
        f"Sent message from {request.source_agent} to {request.target_agent} "
        f"in workflow {workflow_id}"
    )
    
    return MessageResponse(
        message_id=message.id,
        status="sent",
        timestamp=message.timestamp
    )


@router.get("/{workflow_id}/agents/{agent_id}/messages", response_model=MessagesListResponse)
async def get_agent_messages(
    workflow_id: str,
    agent_id: str,
    app_request: Request,
    timeout: float = 1.0,
    max_messages: int = 100
):
    """Retrieve pending messages for an agent.
    
    This endpoint allows agents to retrieve messages sent to them by other
    agents in the workflow. Messages are returned in the order they were sent.
    
    Args:
        workflow_id: The workflow identifier
        agent_id: The agent identifier
        app_request: FastAPI request object
        timeout: Maximum time to wait for messages (seconds)
        max_messages: Maximum number of messages to return
        
    Returns:
        List of messages with metadata
        
    Raises:
        HTTPException: If message queue is not available
    """
    # Get message queue from app state
    if not hasattr(app_request.app.state, 'message_queue'):
        raise HTTPException(
            status_code=503,
            detail="Message queue service not available"
        )
        
    message_queue = app_request.app.state.message_queue
    
    # Receive messages
    messages = await message_queue.receive_messages(
        workflow_id=workflow_id,
        agent_id=agent_id,
        timeout=timeout,
        max_messages=max_messages
    )
    
    # Convert messages to dict format
    message_dicts = []
    for msg in messages:
        message_dicts.append({
            "id": msg.id,
            "source": msg.source_agent,
            "type": msg.message_type,
            "payload": msg.payload,
            "timestamp": msg.timestamp
        })
        
    logger.debug(
        f"Retrieved {len(messages)} messages for agent {agent_id} "
        f"in workflow {workflow_id}"
    )
    
    return MessagesListResponse(
        messages=message_dicts,
        count=len(message_dicts),
        has_more=len(messages) >= max_messages
    )


@router.get("/{workflow_id}/status", response_model=WorkflowStatusResponse)
async def get_workflow_status(
    workflow_id: str,
    app_request: Request
):
    """Get status and statistics for a workflow.
    
    This endpoint provides information about a workflow including active agents,
    request statistics, cache hit rates, and instance assignment.
    
    Args:
        workflow_id: The workflow identifier
        app_request: FastAPI request object
        
    Returns:
        Workflow status and statistics
        
    Raises:
        HTTPException: If workflow manager is not available or workflow not found
    """
    # Get workflow manager from router
    if not hasattr(app_request.app.state, 'router'):
        raise HTTPException(
            status_code=503,
            detail="Router not available"
        )
        
    router = app_request.app.state.router
    
    # Check if router has workflow manager
    if not hasattr(router, 'workflow_manager'):
        raise HTTPException(
            status_code=501,
            detail="Workflow management not supported by current router"
        )
        
    workflow_manager = router.workflow_manager
    
    # Get workflow context
    workflow = await workflow_manager.get_workflow(workflow_id)
    
    if not workflow:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow {workflow_id} not found"
        )
        
    return WorkflowStatusResponse(
        workflow_id=workflow_id,
        created_at=workflow.created_at,
        last_updated=workflow.last_updated,
        active_agents=len(workflow.active_agents),
        total_requests=workflow.total_requests,
        cache_hits=workflow.cache_hits,
        cache_hit_rate=workflow.get_cache_hit_rate(),
        assigned_instance=workflow.assigned_instance
    )


@router.get("/stats")
async def get_workflow_stats(app_request: Request):
    """Get overall workflow system statistics.
    
    This endpoint provides system-wide statistics about workflow usage,
    including total workflows, cache hit rates, and message queue status.
    
    Args:
        app_request: FastAPI request object
        
    Returns:
        System-wide workflow statistics
    """
    stats = {}
    
    # Get workflow manager stats
    if hasattr(app_request.app.state, 'router') and hasattr(app_request.app.state.router, 'get_workflow_stats'):
        router_stats = await app_request.app.state.router.get_workflow_stats()
        stats.update(router_stats)
        
    # Get message queue stats
    if hasattr(app_request.app.state, 'message_queue'):
        queue_stats = await app_request.app.state.message_queue.get_queue_stats()
        stats["message_queue"] = queue_stats
        
    return stats