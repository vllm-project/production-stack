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
