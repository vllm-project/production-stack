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
import random
from typing import Any, Dict, Generator, Set, Tuple

import xxhash

logger = logging.getLogger(__name__)


class TrieNode:
    def __init__(self):
        self.children = {}
        self.endpoints = set()

        # assign a lock for each trie node.
        # this assures that each node will only be accessed by one co-routine
        # at a time.
        self.lock = asyncio.Lock()


class HashTrie:
    def __init__(self, chunk_size: int = 128):
        """
        Initialize the HashTrie.
        Args:
            chunk_size (int): the string chunk size (in terms of # characters)
        """
        self.root = TrieNode()
        self.chunk_size = chunk_size

    def _chunk_and_hash(self, request: str) -> Generator[int, None, None]:
        """
        Chunk and hash the request.
        Args:
            request (str): The request to chunk and hash.
        Returns:
            Generator[int, None, None]: A generator that yields a hash for each
            chunk.
        """

        for i in range(0, len(request), self.chunk_size):
            yield xxhash.xxh64(request[i : i + self.chunk_size]).intdigest()

    async def insert(self, request: str, endpoint: str) -> None:
        """
        Insert the request and endpoint into the trie.
        Args:
            request (str): The request to insert.
            endpoint (str): The endpoint to insert.
        """
        node = self.root
        node.endpoints.add(endpoint)
        for chunk_hash in self._chunk_and_hash(request):
            async with node.lock:
                if chunk_hash not in node.children:
                    node.children[chunk_hash] = TrieNode()
                node = node.children[chunk_hash]
            node.endpoints.add(endpoint)

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
        chunk_hashes = self._chunk_and_hash(request)
        selected_endpoints = available_endpoints

        for i, chunk_hash in enumerate(chunk_hashes):
            async with node.lock:
                if chunk_hash in node.children:

                    node = node.children[chunk_hash]

                    # reached longest prefix match in currently-available endpoints.
                    if not node.endpoints.intersection(selected_endpoints):
                        break

                    match_length += self.chunk_size
                    selected_endpoints = node.endpoints.intersection(selected_endpoints)
                else:
                    break

        return match_length, selected_endpoints
