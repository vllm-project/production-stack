from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from vllm_router.services.batch_service.batch import BatchInfo
from vllm_router.services.files_service.storage import Storage


class BatchProcessor(ABC):
    """Abstract base class for batch request processing"""

    def __init__(self, storage: Storage):
        self.storage = storage

    @abstractmethod
    async def initialize(self):
        """Initialize the batch processor"""
        pass

    @abstractmethod
    async def create_batch(
        self,
        input_file_id: str,
        endpoint: str,
        completion_window: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> BatchInfo:
        """Create a new batch job"""
        pass

    @abstractmethod
    async def retrieve_batch(self, batch_id: str) -> BatchInfo:
        """Retrieve a specific batch job"""
        pass

    @abstractmethod
    async def list_batches(
        self, limit: int = 100, after: str = None
    ) -> List[BatchInfo]:
        """List all batch jobs with pagination"""
        pass

    @abstractmethod
    async def cancel_batch(self, batch_id: str) -> BatchInfo:
        """Cancel a running batch job"""
        pass
