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

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class HashTrieConfig:
    """Configuration for HashTrie with LRU eviction"""

    chunk_size: int = 0
    max_memory_size: int = 0  # GB
    eviction_threshold: float = 0  # start evicting at
    target_utilization: float = 0  # evict down to
    memory_check_request_batch_size: int = 0

    @staticmethod
    def from_defaults(
        chunk_size: int = 128,
        max_memory_size: int = 2,
        eviction_threshold: float = 0.9,
        target_utilization: float = 0.5,
        memory_check_request_batch_size: int = 10,
    ) -> "HashTrieConfig":
        """Create configuration with default values"""
        return HashTrieConfig(
            chunk_size,
            max_memory_size,
            eviction_threshold,
            target_utilization,
            memory_check_request_batch_size,
        )

    @staticmethod
    def from_env() -> "HashTrieConfig":
        """Load configuration from environment variables"""
        return HashTrieConfig(
            chunk_size=int(os.getenv("HASHTRIE_CHUNK_SIZE", "128")),
            max_memory_size=int(os.getenv("PREFIXAWARE_MAX_MEMORY_SIZE_GB", "2")),
            eviction_threshold=float(os.getenv("HASHTRIE_EVICTION_THRESHOLD", "0.9")),
            target_utilization=float(os.getenv("HASHTRIE_TARGET_UTILIZATION", "0.5")),
            memory_check_request_batch_size=int(
                os.getenv("MEMORY_CHECK_REQUEST_BATCH_SIZE", "10")
            ),
        )
