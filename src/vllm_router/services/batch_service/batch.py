from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class BatchStatus(str, Enum):
    """
    Represents the status of a batch job.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class BatchEndpoint(str, Enum):
    """
    Represents the available OpenAI API endpoints for batch requests.

    Ref https://platform.openai.com/docs/api-reference/batch/create#batch-create-endpoint.
    """

    CHAT_COMPLETION = "/v1/chat/completions"
    EMBEDDING = "/v1/embeddings"
    COMPLETION = "/v1/completions"


@dataclass
class BatchRequest:
    """Represents a single request in a batch"""

    input_file_id: str
    endpoint: BatchEndpoint
    completion_window: str
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class BatchInfo:
    """
    Represents batch job information

    Ref https://platform.openai.com/docs/api-reference/batch/object
    """

    id: str
    status: BatchStatus
    input_file_id: str
    created_at: int
    endpoint: str
    completion_window: str
    output_file_id: Optional[str] = None
    error_file_id: Optional[str] = None
    in_progress_at: Optional[int] = None
    expires_at: Optional[int] = None
    finalizing_at: Optional[int] = None
    completed_at: Optional[int] = None
    failed_at: Optional[int] = None
    expired_at: Optional[int] = None
    cancelling_at: Optional[int] = None
    cancelled_at: Optional[int] = None
    total_requests: Optional[int] = None
    completed_requests: int = 0
    failed_requests: int = 0
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert the instance to a dictionary."""
        return {
            "id": self.id,
            "status": self.status.value,
            "input_file_id": self.input_file_id,
            "created_at": self.created_at,
            "endpoint": self.endpoint,
            "completion_window": self.completion_window,
            "output_file_id": self.output_file_id,
            "error_file_id": self.error_file_id,
            "in_progress_at": self.in_progress_at,
            "expires_at": self.expires_at,
            "finalizing_at": self.finalizing_at,
            "completed_at": self.completed_at,
            "failed_at": self.failed_at,
            "expired_at": self.expired_at,
            "cancelling_at": self.cancelling_at,
            "cancelled_at": self.cancelled_at,
            "total_requests": self.total_requests,
            "completed_requests": self.completed_requests,
            "failed_requests": self.failed_requests,
            "metadata": self.metadata,
        }
