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

"""Standardized error response models for API consistency."""

import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Detailed error information."""
    code: str = Field(..., description="Error code identifier")
    message: str = Field(..., description="Human-readable error message")
    field: Optional[str] = Field(None, description="Field name if validation error")
    value: Optional[Any] = Field(None, description="Invalid value if validation error")


class ErrorResponse(BaseModel):
    """Standardized error response format."""
    error: bool = Field(True, description="Always true for error responses")
    error_type: str = Field(..., description="Category of error: validation|service|authentication|authorization|not_found|rate_limit|internal")
    message: str = Field(..., description="Primary error message")
    details: Optional[List[ErrorDetail]] = Field(None, description="Detailed error information")
    request_id: Optional[str] = Field(None, description="Request ID for tracking")
    timestamp: float = Field(default_factory=time.time, description="Error timestamp")
    
    class Config:
        schema_extra = {
            "example": {
                "error": True,
                "error_type": "validation",
                "message": "Invalid input parameters",
                "details": [
                    {
                        "code": "INVALID_FORMAT",
                        "message": "Agent ID must contain only alphanumeric characters",
                        "field": "agent_id",
                        "value": "agent@123"
                    }
                ],
                "request_id": "req_12345",
                "timestamp": 1672531200.0
            }
        }


class ValidationErrorResponse(ErrorResponse):
    """Validation error response with field-specific details."""
    error_type: str = Field("validation", description="Always 'validation' for this response type")
    
    @classmethod
    def from_validation_error(cls, validation_errors: List[Dict[str, Any]], request_id: Optional[str] = None):
        """Create validation error response from Pydantic validation errors."""
        details = []
        
        for error in validation_errors:
            detail = ErrorDetail(
                code=error.get("type", "VALIDATION_ERROR").upper(),
                message=error.get("msg", "Validation failed"),
                field=".".join(str(loc) for loc in error.get("loc", [])) if error.get("loc") else None,
                value=error.get("input")
            )
            details.append(detail)
            
        return cls(
            message=f"Validation failed for {len(details)} field(s)",
            details=details,
            request_id=request_id
        )


class ServiceErrorResponse(ErrorResponse):
    """Service error response for external service failures."""
    error_type: str = Field("service", description="Always 'service' for this response type")
    service_name: Optional[str] = Field(None, description="Name of the failing service")
    retry_after: Optional[int] = Field(None, description="Seconds to wait before retrying")
    
    class Config:
        schema_extra = {
            "example": {
                "error": True,
                "error_type": "service",
                "message": "Message queue service unavailable",
                "service_name": "message_queue",
                "retry_after": 30,
                "request_id": "req_12345",
                "timestamp": 1672531200.0
            }
        }


class AuthenticationErrorResponse(ErrorResponse):
    """Authentication error response."""
    error_type: str = Field("authentication", description="Always 'authentication' for this response type")
    auth_scheme: Optional[str] = Field(None, description="Required authentication scheme")
    
    class Config:
        schema_extra = {
            "example": {
                "error": True,
                "error_type": "authentication",
                "message": "Invalid or missing authentication token",
                "auth_scheme": "Bearer",
                "request_id": "req_12345",
                "timestamp": 1672531200.0
            }
        }


class AuthorizationErrorResponse(ErrorResponse):
    """Authorization error response."""
    error_type: str = Field("authorization", description="Always 'authorization' for this response type")
    required_permission: Optional[str] = Field(None, description="Required permission or role")
    
    class Config:
        schema_extra = {
            "example": {
                "error": True,
                "error_type": "authorization",
                "message": "Insufficient permissions to access this resource",
                "required_permission": "workflow:write",
                "request_id": "req_12345",
                "timestamp": 1672531200.0
            }
        }


class NotFoundErrorResponse(ErrorResponse):
    """Not found error response."""
    error_type: str = Field("not_found", description="Always 'not_found' for this response type")
    resource_type: Optional[str] = Field(None, description="Type of resource that was not found")
    resource_id: Optional[str] = Field(None, description="ID of resource that was not found")
    
    class Config:
        schema_extra = {
            "example": {
                "error": True,
                "error_type": "not_found",
                "message": "Workflow not found",
                "resource_type": "workflow",
                "resource_id": "wf_12345",
                "request_id": "req_12345",
                "timestamp": 1672531200.0
            }
        }


class RateLimitErrorResponse(ErrorResponse):
    """Rate limit error response."""
    error_type: str = Field("rate_limit", description="Always 'rate_limit' for this response type")
    retry_after: int = Field(..., description="Seconds to wait before retrying")
    limit: Optional[int] = Field(None, description="Rate limit threshold")
    remaining: Optional[int] = Field(None, description="Remaining requests in current window")
    reset_time: Optional[float] = Field(None, description="Timestamp when rate limit resets")
    
    class Config:
        schema_extra = {
            "example": {
                "error": True,
                "error_type": "rate_limit",
                "message": "Rate limit exceeded",
                "retry_after": 60,
                "limit": 100,
                "remaining": 0,
                "reset_time": 1672534800.0,
                "request_id": "req_12345",
                "timestamp": 1672531200.0
            }
        }


class InternalErrorResponse(ErrorResponse):
    """Internal server error response."""
    error_type: str = Field("internal", description="Always 'internal' for this response type")
    trace_id: Optional[str] = Field(None, description="Internal trace ID for debugging")
    
    class Config:
        schema_extra = {
            "example": {
                "error": True,
                "error_type": "internal",
                "message": "An internal server error occurred",
                "trace_id": "trace_67890",
                "request_id": "req_12345",
                "timestamp": 1672531200.0
            }
        }


# Utility functions for creating standardized error responses

def create_validation_error(message: str, field: str, value: Any, request_id: Optional[str] = None) -> ValidationErrorResponse:
    """Create a validation error response for a single field."""
    detail = ErrorDetail(
        code="VALIDATION_ERROR",
        message=message,
        field=field,
        value=value
    )
    return ValidationErrorResponse(
        message=f"Validation failed: {message}",
        details=[detail],
        request_id=request_id
    )


def create_service_error(service_name: str, message: str, retry_after: Optional[int] = None, request_id: Optional[str] = None) -> ServiceErrorResponse:
    """Create a service error response."""
    return ServiceErrorResponse(
        message=message,
        service_name=service_name,
        retry_after=retry_after,
        request_id=request_id
    )


def create_not_found_error(resource_type: str, resource_id: str, request_id: Optional[str] = None) -> NotFoundErrorResponse:
    """Create a not found error response."""
    return NotFoundErrorResponse(
        message=f"{resource_type.title()} not found",
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id
    )


def create_rate_limit_error(retry_after: int, limit: Optional[int] = None, remaining: Optional[int] = None, request_id: Optional[str] = None) -> RateLimitErrorResponse:
    """Create a rate limit error response."""
    return RateLimitErrorResponse(
        message="Rate limit exceeded",
        retry_after=retry_after,
        limit=limit,
        remaining=remaining,
        reset_time=time.time() + retry_after,
        request_id=request_id
    )


def create_internal_error(message: str = "An internal server error occurred", trace_id: Optional[str] = None, request_id: Optional[str] = None) -> InternalErrorResponse:
    """Create an internal error response."""
    return InternalErrorResponse(
        message=message,
        trace_id=trace_id,
        request_id=request_id
    )