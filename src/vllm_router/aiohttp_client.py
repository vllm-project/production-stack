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
import aiohttp

from vllm_router.log import init_logger

logger = init_logger(__name__)


class AiohttpClientWrapper:

    async_client = None

    def start(self):
        """Instantiate the client. Call from the FastAPI startup hook."""
        # To fully leverage the router's concurrency capabilities,
        # we set the maximum number of connections to be unlimited.
        connector = aiohttp.TCPConnector(limit=0)
        self.async_client = aiohttp.ClientSession(
            connector=connector, connector_owner=True
        )
        logger.info(f"aiohttp ClientSession instantiated. Id {id(self.async_client)}")

    async def stop(self):
        """Gracefully shutdown. Call from FastAPI shutdown hook."""
        logger.info(
            f"aiohttp async_client.closed: {self.async_client.closed} - Now close it. Id (will be unchanged): {id(self.async_client)}"
        )
        await self.async_client.close()
        logger.info(
            f"aiohttp async_client.closed: {self.async_client.closed}. Id (will be unchanged): {id(self.async_client)}"
        )
        self.async_client = None
        logger.info("aiohttp ClientSession closed")

    def __call__(self):
        """Calling the instantiated AiohttpClientWrapper returns the wrapped singleton."""
        # Ensure we don't use it if not started / running
        assert self.async_client is not None
        return self.async_client
