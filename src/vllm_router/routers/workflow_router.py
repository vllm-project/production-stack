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

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from vllm_router.log import init_logger
from vllm_router.models.error_response import (
    InternalErrorResponse,
    NotFoundErrorResponse,
    ServiceErrorResponse,
    ValidationErrorResponse,
    create_internal_error,
    create_not_found_error,
    create_service_error,
    create_validation_error,
)
from vllm_router.models.workflow import AgentMessage

logger = init_logger(__name__)

router = APIRouter(prefix="/v1/workflows", tags=["workflows"])


class SendMessageRequest(BaseModel):
    """Request model for sending agent messages."""
    source_agent: str = Field(
        ..., description="Source agent ID", min_length=1, max_length=100
    )
    target_agent: str = Field(
        ..., description="Target agent ID", min_length=1, max_length=100
    )
    message_type: str = Field(
        "data", description="Message type: data|signal|query|response"
    )
    payload: Dict[str, Any] = Field(..., description="Message payload")
    ttl: int = Field(
        300, description="Message TTL in seconds", ge=1, le=86400
    )  # 1 second to 24 hours
    
    @field_validator('message_type')
    def validate_message_type(cls, v):
        allowed_types = {'data', 'signal', 'query', 'response'}
        if v not in allowed_types:
            raise ValueError(
                f'message_type must be one of: {", ".join(allowed_types)}'
            )
        return v
        
    @field_validator('source_agent', 'target_agent')
    def validate_agent_id(cls, v):
        # Agent IDs should be alphanumeric with hyphens/underscores
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError(
                'Agent ID must contain only alphanumeric characters, '
                'hyphens, and underscores'
            )
        return v
        
    @field_validator('payload')
    def validate_payload_size(cls, v):
        # Rough size check (actual JSON size will be larger)
        import json
        try:
            payload_str = json.dumps(v)
            if len(payload_str) > 1024 * 1024:  # 1MB limit
                raise ValueError('Payload exceeds maximum size of 1MB')
        except (TypeError, ValueError) as e:
            if 'Payload exceeds maximum size' in str(e):
                raise
            raise ValueError('Payload must be JSON serializable')
        return v


class MessageResponse(BaseModel):
    """Response model for message operations."""
    message_id: str
    status: str
    timestamp: float
    
    class Config:
        schema_extra = {
            "example": {
                "message_id": "msg_12345",
                "status": "sent",
                "timestamp": 1672531200.0
            }
        }


class MessagesListResponse(BaseModel):
    """Response model for listing messages."""
    messages: List[Dict[str, Any]]
    count: int
    has_more: bool = False
    
    class Config:
        schema_extra = {
            "example": {
                "messages": [
                    {
                        "id": "msg_12345",
                        "source": "agent_1",
                        "type": "data",
                        "payload": {"result": "analysis complete"},
                        "timestamp": 1672531200.0
                    }
                ],
                "count": 1,
                "has_more": False
            }
        }


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
    
    class Config:
        schema_extra = {
            "example": {
                "workflow_id": "wf_12345",
                "created_at": 1672531200.0,
                "last_updated": 1672534800.0,
                "active_agents": 3,
                "total_requests": 42,
                "cache_hits": 28,
                "cache_hit_rate": 0.67,
                "assigned_instance": "http://engine1.example.com"
            }
        }


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
        workflow_id: The workflow identifier (alphanumeric, hyphens, underscores only, max 100 chars)
        request: Message details including source, target, and payload
        app_request: FastAPI request object for accessing app state
        
    Returns:
        MessageResponse with message ID and status
        
    Raises:
        HTTPException: If message queue is not available, validation fails, or message fails to send
    """
    
    # Validate workflow_id format
    import re
    if not re.match(r'^[a-zA-Z0-9_-]+$', workflow_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid workflow_id format. Must contain only alphanumeric characters, hyphens, and underscores."
        )
    
    # Validate workflow_id length
    if len(workflow_id) > 100:
        raise HTTPException(status_code=400, detail="workflow_id too long (max 100 characters)")
    # Get message queue from app state  
    if not hasattr(app_request.app.state, 'message_queue'):
        error_response = create_service_error(
            service_name="message_queue",
            message="Message queue service not available"
        )
        raise HTTPException(
            status_code=503,
            detail=error_response.dict()
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
    
    # Send message with error handling
    try:
        success = await message_queue.send_message(message)
        
        if not success:
            raise HTTPException(
                status_code=503,
                detail="Failed to send message - queue may be full or message too large"
            )
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal error while sending message"
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
    timeout: float = Query(
        1.0, ge=0.1, le=30.0, description="Timeout in seconds (0.1-30.0)"
    ),
    max_messages: int = Query(
        100, ge=1, le=1000, description="Max messages to return (1-1000)"
    )
):
    """Retrieve pending messages for an agent.
    
    This endpoint allows agents to retrieve messages sent to them by other
    agents in the workflow. Messages are returned in the order they were sent.
    
    Args:
        workflow_id: The workflow identifier (alphanumeric, hyphens, underscores only)
        agent_id: The agent identifier (alphanumeric, hyphens, underscores only)
        app_request: FastAPI request object
        timeout: Maximum time to wait for messages (0.1-30.0 seconds)
        max_messages: Maximum number of messages to return (1-1000)
        
    Returns:
        List of messages with metadata
        
    Raises:
        HTTPException: If message queue is not available or validation fails
    """
    
    # Validate workflow_id and agent_id format
    import re
    if not re.match(r'^[a-zA-Z0-9_-]+$', workflow_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid workflow_id format. Must contain only alphanumeric characters, hyphens, and underscores."
        )
    if not re.match(r'^[a-zA-Z0-9_-]+$', agent_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid agent_id format. Must contain only alphanumeric characters, hyphens, and underscores."
        )
    
    # Validate ID lengths
    if len(workflow_id) > 100:
        raise HTTPException(status_code=400, detail="workflow_id too long (max 100 characters)")
    if len(agent_id) > 100:
        raise HTTPException(status_code=400, detail="agent_id too long (max 100 characters)")
    # Get message queue from app state  
    if not hasattr(app_request.app.state, 'message_queue'):
        error_response = create_service_error(
            service_name="message_queue",
            message="Message queue service not available"
        )
        raise HTTPException(
            status_code=503,
            detail=error_response.dict()
        )
        
    message_queue = app_request.app.state.message_queue
    
    # Receive messages with error handling
    try:
        messages = await message_queue.receive_messages(
            workflow_id=workflow_id,
            agent_id=agent_id,
            timeout=timeout,
            max_messages=max_messages
        )
    except Exception as e:
        logger.error(f"Error receiving messages: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal error while receiving messages"
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
        workflow_id: The workflow identifier (alphanumeric, hyphens, underscores only, max 100 chars)
        app_request: FastAPI request object
        
    Returns:
        Workflow status and statistics
        
    Raises:
        HTTPException: If workflow manager is not available, validation fails, or workflow not found
    """
    
    # Validate workflow_id format
    import re
    if not re.match(r'^[a-zA-Z0-9_-]+$', workflow_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid workflow_id format. Must contain only alphanumeric characters, hyphens, and underscores."
        )
    
    # Validate workflow_id length
    if len(workflow_id) > 100:
        raise HTTPException(status_code=400, detail="workflow_id too long (max 100 characters)")
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
    
    # Get workflow context with error handling
    try:
        workflow = await workflow_manager.get_workflow(workflow_id)
        
        if not workflow:
            raise HTTPException(
                status_code=404,
                detail=f"Workflow {workflow_id} not found"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving workflow {workflow_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal error while retrieving workflow"
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
    
    # Get workflow manager stats with error handling
    try:
        if hasattr(app_request.app.state, 'router') and hasattr(app_request.app.state.router, 'get_workflow_stats'):
            router_stats = await app_request.app.state.router.get_workflow_stats()
            stats.update(router_stats)
    except Exception as e:
        logger.error(f"Error getting router stats: {e}")
        stats["router_error"] = "Failed to retrieve router statistics"
        
    # Get message queue stats with error handling
    try:
        if hasattr(app_request.app.state, 'message_queue'):
            queue_stats = await app_request.app.state.message_queue.get_queue_stats()
            stats["message_queue"] = queue_stats
    except Exception as e:
        logger.error(f"Error getting queue stats: {e}")
        stats["queue_error"] = "Failed to retrieve message queue statistics"
        
    # Ensure we always return valid stats
    if not stats:
        stats = {
            "status": "no_data",
            "message": "No workflow statistics available"
        }
        
    return stats