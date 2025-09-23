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

import asyncio
import logging
import os
from collections import OrderedDict
from typing import Dict, Generator, Optional, Set, Tuple

import psutil
import xxhash

from .config import HashTrieConfig

logger = logging.getLogger(__name__)


class NodeMetadata:
    """Metadata for nodes tracked in LRU cache"""

    def __init__(self, parent: "TrieNode", child_hash: int):
        self.parent = parent
        self.child_hash = child_hash


class TrieNode:
    def __init__(self):
        self.children: Dict[int, "TrieNode"] = {}
        self.endpoints: Set[str] = set()

        # assign a lock for each trie node.
        # this assures that each node will only be accessed by one co-routine
        # at a time.
        self.lock = asyncio.Lock()


class HashTrie:
    def __init__(self, config: Optional[HashTrieConfig] = None):
        """
        Initialize the HashTrie with LRU eviction based on system memory pressure.
        Args:
            config (HashTrieConfig): Configuration for the HashTrie
        """
        self.config = config or HashTrieConfig.from_defaults()
        self.root = TrieNode()

        # HashTrie LRU
        self.node_cache = OrderedDict[TrieNode, NodeMetadata]()
        # eviction threshold
        self.memory_threshold_mb = (
            self.config.max_memory_size * 1024 * self.config.eviction_threshold
        )
        # eviction percentage
        self.eviction_target_percentage = 1.0 - self.config.target_utilization
        self.current_memory_mb = 0.0
        self.operation_count = 0
        # ensure that eviction is performed by only one co-routine
        self.eviction_lock = asyncio.Lock()

    def _chunk_and_hash(self, request: str) -> Generator[int, None, None]:
        """
        Chunk and hash the request.
        Args:
            request (str): The request to chunk and hash.
        Returns:
            Generator[int, None, None]: A generator that yields a hash for each
            chunk.
        """
        for i in range(0, len(request), self.config.chunk_size):
            chunk = request[i : i + self.config.chunk_size]
            yield xxhash.xxh64(chunk).intdigest()

    async def insert(self, request: str, endpoint: str) -> None:
        """
        Insert request-endpoint mapping with LRU tracking and memory pressure monitoring.
        Args:
            request (str): The request to insert.
            endpoint (str): The endpoint to insert.
        """
        node = self.root
        async with node.lock:
            node.endpoints.add(endpoint)

        path_nodes = [(self.root, None)]  # (node, hash_to_reach_it)

        for chunk_hash in self._chunk_and_hash(request):
            async with node.lock:
                if chunk_hash not in node.children:
                    node.children[chunk_hash] = TrieNode()
                node = node.children[chunk_hash]
                path_nodes.append((node, chunk_hash))

            async with node.lock:
                node.endpoints.add(endpoint)

        # add nodes to LRU in reverse order of insert which ensures child nodes are always evicted
        # before parent nodes. Parent node will definitely be accessed when a child node is matched.
        # Thus evicting from child nodes should have least impact.
        for i in range(len(path_nodes) - 1, 0, -1):  # Skip root (index 0)
            current_node, child_hash = path_nodes[i]
            parent_node, _ = path_nodes[i - 1]

            if current_node not in self.node_cache:
                # add new node (appears older due to reverse order)
                self.node_cache[current_node] = NodeMetadata(
                    parent=parent_node, child_hash=child_hash
                )
            else:
                self.node_cache.move_to_end(current_node)

        async with self.eviction_lock:
            # Track operations and check if eviction is needed
            self.operation_count = (
                self.operation_count + 1
            ) % self.config.memory_check_request_batch_size

            # Check if we should evict
            if self.operation_count == 0:
                try:
                    process = psutil.Process(os.getpid())
                    memory_mb = process.memory_info().rss / (1024 * 1024)

                    # python may not release the memory back to OS after GC thus the same memory block will
                    # be reused to create new nodes. Skip the eviction if memory usage does not change to
                    # prevent duplicate evictions
                    if memory_mb != self.current_memory_mb:
                        self.current_memory_mb = memory_mb
                        if memory_mb > self.memory_threshold_mb:
                            await self.batch_evict(self.eviction_target_percentage)
                    else:
                        logger.info(
                            f"Eviction skipped - no memory change detected: {memory_mb:.1f}MB"
                        )
                except Exception as e:
                    logger.error(f"Eviction failed - error message: {e}")

    async def longest_prefix_match(
        self, request: str, available_endpoints: Set[str] = set()
    ) -> Tuple[int, Set[str]]:
        """
        Find the longest matching prefix using hashed chunks.
        Args:
            request (str): The request to find the longest matching prefix.
            available_endpoints (Set[str]): The endpoints that are available.
        """
        node = self.root
        match_length = 0
        selected_endpoints = available_endpoints

        for chunk_hash in self._chunk_and_hash(request):
            async with node.lock:
                node = node.children.get(chunk_hash)
            if not node:
                break
            async with node.lock:
                endpoints = node.endpoints.copy()
            intersection = endpoints.intersection(selected_endpoints)
            # reached longest prefix match in currently-available endpoints.
            if not intersection:
                break
            match_length += self.config.chunk_size
            selected_endpoints = intersection

        return match_length, selected_endpoints

    async def batch_evict(self, eviction_percentage) -> None:
        """
        Manually evict a percentage of LRU nodes.

        Args:
            eviction_percentage: Percentage of nodes to evict
        """
        if len(self.node_cache) == 0:
            return

        initial_count = len(self.node_cache)
        target_evictions = max(1, int(initial_count * eviction_percentage))
        evict_nodes = []
        for node in list(self.node_cache.keys())[:target_evictions]:
            evict_nodes.append(node)

        evicted_count = 0
        for evict_node in evict_nodes:
            if evict_node in self.node_cache:
                await self._evict_node(evict_node)
                evicted_count += 1

        logger.info(
            f"Batch eviction completed - evicted {evicted_count} out of {initial_count} nodes"
        )

    async def _evict_node(self, node: TrieNode) -> None:
        """
        Evict a single node

        Args:
            node: the HashTrie node to be evicted
        """
        if node not in self.node_cache:
            return

        node_metadata = self.node_cache[node]
        parent_node = node_metadata.parent
        child_hash = node_metadata.child_hash

        # Remove from parent's children list
        async with parent_node.lock:
            if child_hash in parent_node.children:
                del parent_node.children[child_hash]

        # Remove from cache
        del self.node_cache[node]
